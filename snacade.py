import traceback
import logging
import random
from uuid import uuid4
from enum import auto
from pathlib import Path
from queue import Queue
import json
import bisect

import adsk.core, adsk.fusion, adsk.cam

from .fusion_addin_framework import fusion_addin_framework as faf
from .voxler import voxler as vox

from .appdirs import appdirs

from game import Game

### GLOBALS ###
n_scores_displayed = 5
screen_offsets = {"left": 3, "right": 1, "top": 4, "botton": 3}
horizontal_scaling = 1.2  # to provent overlapping of commadn inputs
n_speed_levels = 5
initial_speed_level = 2
max_wait_time = 0.5
min_wait_time = 0.1
initial_block_size = 10
scores_path = str(Path(appdirs.user_state_dir("snacade")) / "highscores.json")


def set_camera(game):
    faf.utils.set_camera(
        plane=game.plane,
        horizontal_borders=(
            -screen_offsets["left"] * game.world.grid_size,
            (game.width + screen_offsets["right"])
            * horizontal_scaling
            * game.world.grid_size,
        ),
        vertical_borders=(
            -screen_offsets["botton"] * game.world.grid_size,
            (game.height + screen_offsets["top"]) * game.world.grid_size,
        ),
    )


### INTER HANDLER SHARED VARIABLES ###
# varibale which are created in an event handler and need to be accessed from
# different event handler(s) as well
addin = None
game = None
command = None
mover_event_id = None
execution_queue = Queue()


class InputIds(faf.utils.InputIdsBase):
    ControlsGroup = auto()
    Play = auto()
    Pause = auto()
    Reset = auto()
    SettingsGroup = auto()
    BlockSize = auto()
    KeepBodies = auto()
    HighscoresGroup = auto()
    HighscoresHeading = auto()
    SpeedSlider = auto()
    MazeDropdown = auto()


class GameUI:
    def __init__(self, command):
        self.command = command

        command.isOKButtonVisible = False
        command.cancelButtonText = "Exit"

        self._create_controls_group()
        self._create_settings_group()
        self._create_highscores_group()

    def _create_settings_group(self):
        self.settings_group = self.command.commandInputs.addGroupCommandInput(
            InputIds.SettingsGroup.value, "Settings"
        )

        self.maze_dropdown = self.settings_group.children.addDropDownCommandInput(
            InputIds.MazeDropdown.value,
            "World",
            adsk.core.DropDownStyles.TextListDropDownStyle,
        )
        for maze_name in Game.start_configs.keys():
            self.maze_dropdown.listItems.add(maze_name, False)
        self.maze_dropdown.listItems.item(0).isSelected = True

        self.speed_slider = (
            self.settings_group.children.addIntegerSliderListCommandInput(
                InputIds.SpeedSlider.value,
                "Speed",
                list(range(n_speed_levels)),
                False,
            )
        )
        self.speed_slider.setText("slow", "fast")
        self.speed_slider.valueOne = initial_speed_level

        self.block_size_input = self.settings_group.children.addValueInput(
            InputIds.BlockSize.value,
            "Block size",
            "mm",
            adsk.core.ValueInput.createByReal(initial_block_size),
        )
        self.block_size_input.tooltip = "Side length of single block/voxel."

        self.keep_blocks_input = self.settings_group.children.addBoolValueInput(
            InputIds.KeepBodies.value, "Keep blocks", True, "", True
        )
        self.keep_blocks_input.tooltip = (
            "Determines if the blocks will be kept after leaving the game."
        )
        # settings_group.isExpanded = False

    def _create_controls_group(self):
        self.controls_group = self.command.commandInputs.addGroupCommandInput(
            InputIds.ControlsGroup.value, "Controls"
        )

        self.play_button = self.controls_group.children.addBoolValueInput(
            InputIds.Play.value,
            "Play",
            True,
            str(Path(__file__).parent / "resources" / "play_button"),
            False,
        )
        self.play_button.tooltip = "Start/Continue the game."

        self.pause_button = self.controls_group.children.addBoolValueInput(
            InputIds.Pause.value,
            "Pause",
            True,
            str(Path(__file__).parent / "resources" / "pause_button"),
            False,
        )
        self.pause_button.tooltip = "Pause the game."
        self.pause_button.isEnabled = False

        self.reset_button = self.controls_group.children.addBoolValueInput(
            InputIds.Reset.value,
            "Reset",
            True,
            str(Path(__file__).parent / "resources" / "redo_button"),
            False,
        )
        self.reset_button.tooltip = "Reset the game"

        self.control_buttons = [self.play_button, self.pause_button, self.reset_button]

    def _create_highscores_group(self):
        self.highscores_group = self.command.commandInputs.addGroupCommandInput(
            InputIds.HighscoresGroup.value, "Highscores"
        )

        self.highscore_heading = self.highscores_group.children.addTextBoxCommandInput(
            InputIds.HighscoresHeading.value, "Rank", "Points", 1, True
        )

        scores = faf.utils.get_json_from_file(scores_path, [])
        self.highscore_texts = [
            self.highscores_group.children.addTextBoxCommandInput(
                InputIds.HighscoresHeading.value + str(rank),
                str(rank + 1),
                str(scores[rank]) if rank < len(scores) else "-",
                1,
                True,
            )
            for rank in range(n_scores_displayed)
        ]

        self.highscores_group.isExpanded = False

    def _unclick_control_buttons(self):
        for button in self.control_buttons:
            button.value = False

    def start_state(self):
        self.play_button.isEnabled = True
        self.pause_button.isEnabled = False
        self.reset_button.isEnabled = True
        self._unclick_control_buttons()

        self.block_size_input.isEnabled = True

        self.maze_dropdown.isEnabled = True

    def pause_state(self):
        self.play_button.isEnabled = True
        self.pause_button.isEnabled = False
        self.reset_button.isEnabled = True
        self._unclick_control_buttons()

        self.block_size_input.isEnabled = True

        self.maze_dropdown.isEnabled = False

    def running_state(self):
        self.play_button.isEnabled = False
        self.pause_button.isEnabled = True
        self.reset_button.isEnabled = True
        self._unclick_control_buttons()

        self.block_size_input.isEnabled = False

        self.maze_dropdown.isEnabled = False

    def game_over_state(self):
        self.play_button.isEnabled = False
        self.pause_button.isEnabled = False
        self.reset_button.isEnabled = True
        self._unclick_control_buttons()

        self.block_size_input.isEnabled = True

        self.maze_dropdown.isEnabled = False

    def update_score(self):
        pass

    def _update_leaderboard(self):
        pass


def on_created(event_args: adsk.core.CommandCreatedEventArgs):
    command = event_args.command

    # turn of parametric mode
    design = adsk.core.Application.get().activeDocument.design
    if design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        dialog_result = adsk.core.Application.get().userInterface.messageBox(
            "WARNING: Snacade can only be played in direct design mode.\n"
            + "Do you want to switch to direct design mode by disabling the timeline?\n\n"
            + "The timeline and all design history will be removed, \n"
            + "and further operations will not be captured in the timeline.",
            "Warning",
            adsk.core.MessageBoxButtonTypes.YesNoButtonType,
        )
        if dialog_result == adsk.core.DialogResults.DialogYes:
            design.designType = adsk.fusion.DesignTypes.DirectDesignType
        else:
            return

    # create the command inputs
    game_ui = GameUI(command)

    # set up the game and world instacen
    comp = faf.utils.new_comp("snacade")
    design.rootComponent.allOccurrencesByComponent(comp).item(0).activate()
    world = vox.VoxelWorld(initial_block_size, comp, offset=(1.5, 1.5))

    global game
    game = Game(
        world,
        game_ui,
        mover_event_id,
    )

    # set the camera
    set_camera(game)

    # does not work because command hasnt been created yet
    # event_args.command.doExecute(False)
    # but updating world / creating bodies works in creaed handler (but not in keyDown handler)
    progress_dialog = adsk.core.Application.get().userInterface.createProgressDialog()
    progress_dialog.message = "Building the world (%p%)"
    progress_dialog.title = "Building the world"
    game.update_world(progress_dialog)


def on_execute(event_args: adsk.core.CommandEventArgs):
    while not execution_queue.empty():
        execution_queue.get()()


def on_input_changed(event_args: adsk.core.InputChangedEventArgs):
    # inputs = event_args.firingEvent.sender.commandInputs
    # inputs = event_args.inputs # !!! do NOT use this because of bug
    # (will only contain inputs of the same input group)

    {
        InputIds.Play.value: game.play,
        InputIds.Pause.value: game.pause,
        InputIds.Reset.value: game.reset,
    }.get(event_args.input.id, lambda: None)()

    if event_args.input.id == InputIds.BlockSize.value:
        execution_queue.put(game.world.clear)
        game.world.grid_size = event_args.input.value
        set_camera(game)

    if event_args.input.id == InputIds.SpeedSlider.value:
        game.speed = level_to_time_delta(event_args.input.valueOne)

    if event_args.input.id == InputIds.MazeDropdown.value:
        game.build_start_state()

    execution_queue.put(game.update_world)

    command.doExecute(False)


def on_key_down(event_args: adsk.core.KeyboardEventArgs):
    {
        adsk.core.KeyCodes.UpKeyCode: game.up,
        adsk.core.KeyCodes.LeftKeyCode: game.left,
        adsk.core.KeyCodes.RightKeyCode: game.right,
        adsk.core.KeyCodes.DownKeyCode: game.down,
    }.get(event_args.keyCode, lambda: None)()

    execution_queue.put(game.update_world)
    event_args.firingEvent.sender.doExecute(False)


def on_destroy(event_args: adsk.core.CommandEventArgs):
    game.pause()
    game.stop()

    if not event_args.command.commandInputs.itemById(InputIds.KeepBodies.value).value:
        # game.world.clear()
        faf.utils.delete_comp(comp)


def on_periodic_move(event_args: adsk.core.CustomEventArgs):
    game.move_snake()
    # game.update_world() # --> somehow ont working --> therfore:
    # command cant be retrieved from args --> global instance necessary
    if command.isValid:
        execution_queue.put(game.update_world)
        command.doExecute(False)
    # results in fusion work --> must be executed from custom event handler


### ENTRY POINT ###
def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        faf.utils.create_logger(
            faf.__name__,
            [logging.StreamHandler(), faf.utils.TextPaletteLoggingHandler()],
        )

        global addin
        addin = faf.FusionAddin()
        workspace = faf.Workspace(addin)
        tab = faf.Tab(workspace)
        panel = faf.Panel(tab, id="FunPanelId", name="Fun")
        control = faf.Control(panel, isPromoted=True, isPromotedByDefault=True)
        global mover_event_id
        mover_event_id = str(uuid4())
        cmd = faf.AddinCommand(
            control,
            name="snacade",
            commandCreated=on_created,
            inputChanged=on_input_changed,
            keyDown=on_key_down,
            execute=on_execute,
            destroy=on_destroy,
            customEventHandlers={mover_event_id: on_periodic_move},
        )

    except:
        msg = "Failed:\n{}".format(traceback.format_exc())
        if ui:
            ui.messageBox(msg)
        print(msg)


def stop(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        addin.stop()
    except:
        msg = "Failed:\n{}".format(traceback.format_exc())
        if ui:
            ui.messageBox(msg)
        print(msg)