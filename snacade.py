import traceback
import logging
from uuid import uuid4
from pathlib import Path
from queue import Queue

import adsk.core, adsk.fusion, adsk.cam

from .fusion_addin_framework import fusion_addin_framework as faf
from .voxler import voxler as vox

from .appdirs import appdirs

from .src.game import Game
from .src.ui import GameUI, InputIds

### GLOBALS (Settings) ###
N_SCORES_DISPLAYED = 5
SCORES_PATH = str(Path(appdirs.user_state_dir("snacade")) / "highscores.json")
N_SPEED_LEVELS = 5
INITIAL_SPEED_LEVEL = 2
INITIAL_BLOCK_SIZE = 10
NO_SCORE_SYMBOL = "-"
RESOURCE_FOLDER = Path(__file__).parent / "resources"

MIN_MOVE_WAIT_TIME = 0.1
MAX_MOVE_WAIT_TIME = 0.5

SCREEN_OFFSETS = {"left": 3, "right": 1, "top": 4, "botton": 3}
HORZIONTAL_SCALING = 1.2  # to provent overlapping of commadn inputs


def _set_camera(height, width, grid_size, plane):
    faf.utils.set_camera(
        plane=plane,
        horizontal_borders=(
            -SCREEN_OFFSETS["left"] * grid_size,
            (width + SCREEN_OFFSETS["right"]) * HORZIONTAL_SCALING * grid_size,
        ),
        vertical_borders=(
            -SCREEN_OFFSETS["botton"] * grid_size,
            (height + SCREEN_OFFSETS["top"]) * grid_size,
        ),
    )


### INTER HANDLER SHARED VARIABLES ###
# varibale which are created in an event handler and need to be accessed from
# different event handler(s) as well
addin = None
game = None
command = None
comp = None
mover_event_id = None
execution_queue = Queue()


def on_created(event_args: adsk.core.CommandCreatedEventArgs):
    global command
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
    game_ui = GameUI(
        command,
        RESOURCE_FOLDER,
        SCORES_PATH,
        N_SCORES_DISPLAYED,
        N_SPEED_LEVELS,
        INITIAL_SPEED_LEVEL,
        INITIAL_BLOCK_SIZE,
        NO_SCORE_SYMBOL,
    )

    # set up the game and world instacen
    global comp
    comp = faf.utils.new_comp("snacade")
    design.rootComponent.allOccurrencesByComponent(comp).item(0).activate()
    world = vox.VoxelWorld(game_ui.block_size_input.value, comp, offset=(1.5, 1.5))

    global game
    game = Game(world, game_ui, mover_event_id, MIN_MOVE_WAIT_TIME, MAX_MOVE_WAIT_TIME)

    # set the camera
    _set_camera(
        game.height, game.width, game.game_ui.block_size_input.value, game.plane
    )

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
        _set_camera(game.height, game.width, game.world.gridsize, game.plane)

    if event_args.input.id == InputIds.SpeedSlider.value:
        game.speed = event_args.input.valueOne

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