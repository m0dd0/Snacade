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

n_scores_displayed = 5
screen_offsets = {"left": 1, "right": 1, "top": 1, "botton": 1}
n_speed_levels = 5
initial_speed_level = 2
max_wait_time = 0.5
min_wait_time = 0.1
initial_block_size = 10
scores_path = str(Path(appdirs.user_state_dir("snacade")) / "highscores.json")


def level_to_time_delta(level):
    delta_time = (max_wait_time - min_wait_time) / (n_speed_levels - 1)
    return max_wait_time - level * delta_time


class Snake:
    _allowed_moves = ["left", "right", "up", "down"]

    def __init__(self, head, orientation, body_length):
        self._current_direction = orientation
        self._elements = [head] + [
            self._move_coordinate(head, self._current_direction, -i)
            for i in range(1, body_length)
        ]

        self._last_tail = None
        self._direction_setable = True

    def _move_coordinate(self, coord, direction, i=1):
        if direction not in self._allowed_moves:
            raise ValueError()

        x_dir, y_dir = {
            "left": (-1, 0),
            "right": (1, 0),
            "up": (0, 1),
            "down": (0, -1),
        }[direction]

        return (coord[0] + x_dir * i, coord[1] + y_dir * i)

    def eat(self):
        if self._last_tail is None:
            return False
        self._elements.append(self._last_tail)
        self._last_tail = None
        return self._elements[-1]

    def move(self):
        self._elements.insert(
            0, self._move_coordinate(self._elements[0], self._current_direction)
        )
        self._last_tail = self._elements.pop()
        self._direction_setable = True

    def undo_move(self):
        self._elements = self._elements[1:] + [self._last_tail]
        self._last_tail = None

    def set_direction(self, new_direction):
        if new_direction not in self._allowed_moves:
            raise ValueError()
        if self._direction_setable:
            if (self._current_direction, new_direction) not in [
                ("up", "down"),
                ("down", "up"),
                ("left", "right"),
                ("right", "left"),
            ]:
                self._current_direction = new_direction
                self._direction_setable = False

    @property
    def head(self):
        return self._elements[0]

    @property
    def body(self):
        return self._elements[1:]


class Game:
    start_config_a = {
        "height": 20,
        "width": 50,
        "obstacles": {(20, 5), (21, 5), (22, 5)},
        "snake_head": (25, 10),
        "snake_direction": "up",
        "snake_length": 5,
    }

    maze_voxel_style = {
        "voxel_class": vox.DirectCube,
        "color": None,
        "appearance": "Steel - Satin",
        "name": "maze voxel",
    }
    snake_body_voxel_style = {
        "voxel_class": vox.DirectSphere,
        "color": None,
        "appearance": "Steel - Satin",
        "name": "snake voxel",
    }
    snake_head_voxel_style = {
        "voxel_class": vox.DirectSphere,
        "color": (255, 0, 0, 255),
        "appearance": "Steel - Satin",
        "name": "snake voxel",
    }
    food_voxel_style = {
        "voxel_class": vox.DirectSphere,
        "color": (0, 255, 0, 255),
        "appearance": "Steel - Satin",
        "name": "food voxel",
    }

    # state_transitions = {
    #     "paused": ["running", "paused"],
    #     "running": ["paused", "game_over"],
    #     "game_over": ["paused"],
    # }

    def __init__(self, world, start_config, speed, mover_event_id):
        self.world = world

        self._speed = speed

        self._mover_thread = faf.utils.PeriodicExecuter(
            speed, lambda: adsk.core.Application.get().fireCustomEvent(mover_event_id)
        )

        self._state = "paused"

        self._score = None
        self._height = None
        self._width = None
        self._plane = None
        self._maze = None
        self._possible_food_positions = None
        self._snake = None
        self._food = None

        self._start_config = start_config
        self._build_start_state()

    def _build_start_state(self):
        self._score = 0

        self._height = self._start_config["height"]
        self._width = self._start_config["width"]

        self._plane = "xy"  # TODO setable

        self._maze = set().union(
            {(i, 0) for i in range(self._width)},
            {(i, self._height - 1) for i in range(self._width)},
            {(0, j) for j in range(self._height)},
            {(self._width - 1, j) for j in range(self._height)},
            self._start_config["obstacles"],
        )
        # (0,0) -> (width-1,0)
        # (0,height-1) -> (width-1, height)
        # (0,0) -> (0,height-1)
        # (width-1,0) -> (width,height-1)

        # use list to enable the use of random.choice
        self._possible_food_positions = {
            (i, j)
            for i in range(1, self._width - 1)
            for j in range(1, self._height - 1)
        } - self._start_config["obstacles"]

        self._snake = Snake(
            self._start_config["snake_head"],
            self._start_config["snake_direction"],
            self._start_config["snake_length"],
        )

        self._food = self._find_food_position()

    def _find_food_position(self):
        return random.choice(
            list(
                self._possible_food_positions
                - {self._snake.head}
                - set(self._snake.body)
            )
        )

    def move_snake(self):
        self._snake.move()
        if self._snake.head in self._maze or self._snake.head in self._snake.body:
            self._mover_thread.pause()
            self._snake.undo_move()
            self._state = "over"
            # TODO this is hacky, better use a InputField class as a attribute of
            # the game or similar
            command.commandInputs.itemById(InputIds.Pause.value).isEnabled = False
            command.commandInputs.itemById(InputIds.BlockSize.value).isEnabled = True

            scores = faf.utils.get_json_from_file(str(scores_path), [])
            achieved_rank = len(scores) - bisect.bisect_right(scores[::-1], self._score)
            scores.insert(achieved_rank, self._score)
            with open(scores_path, "w") as f:
                json.dump(scores, f, indent=4)

            if achieved_rank < n_scores_displayed:
                msg = f"GAME OVER\n\nYou made the {faf.utils.make_ordinal(achieved_rank+1)} place in the ranking!"
                for rank in range(n_scores_displayed):
                    command.commandInputs.itemById(
                        InputIds.HighscoresHeading.value + str(rank)
                    ).text = str(scores[rank] if rank < len(scores) else "-")
            else:
                msg = "GAME OVER"
            adsk.core.Application.get().userInterface.messageBox(msg)

        if self._snake.head == self._food:
            self._snake.eat()
            self._food = self._find_food_position()
            self._score += 1

    def update_world(self, *args, **kwargs):
        # TODO adapt for setable drawing plane
        self.world.update(
            {
                **{(*c, 0): self.maze_voxel_style for c in self._maze},
                **{(*c, 0): self.snake_body_voxel_style for c in self._snake.body},
                **{(*self._snake.head, 0): self.snake_head_voxel_style},
                **{(*self._food, 0): self.food_voxel_style},
            },
            *args,
            **kwargs,
        )

    def left(self):
        self._snake.set_direction("left")

    def right(self):
        self._snake.set_direction("right")

    def up(self):
        self._snake.set_direction("up")

    def down(self):
        self._snake.set_direction("down")

    def play(self):
        if self._state == "paused":
            self._mover_thread.start()
            self._state = "running"

    def pause(self):
        if self._state == "running":
            self._mover_thread.pause()
            self._state = "paused"

    def reset(self):
        if self._state in ("running", "paused", "over"):
            self._mover_thread.reset()
            self._mover_thread.pause()
            self._build_start_state()
            self._state = "paused"

    def stop(self):
        self._mover_thread.kill()

    @property
    def height(self):
        return self._height

    @property
    def width(self):
        return self._width

    @property
    def plane(self):
        return self._plane

    @property
    def state(self):
        return self._state

    @property
    def speed(self):
        return self._speed

    @speed.setter
    def speed(self, new_speed):
        self._speed = new_speed
        self._mover_thread.interval = new_speed


# varibale which are created in an event handler and need to be accessed from
# different event handler(s) as well
addin = None
game = None
mover_event_id = None
command = None
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


def on_execute(event_args: adsk.core.CommandEventArgs):
    while not execution_queue.empty():
        execution_queue.get()()


def on_input_changed(event_args: adsk.core.InputChangedEventArgs):
    inputs = event_args.firingEvent.sender.commandInputs
    # inputs = event_args.inputs # !!! do NOT use this because of bug
    # (will only contain inputs of the same input group)

    {
        InputIds.Play.value: game.play,
        InputIds.Pause.value: game.pause,
        InputIds.Reset.value: game.reset,
    }.get(event_args.input.id, lambda: None)()

    all_button_ids = [InputIds.Play.value, InputIds.Pause.value, InputIds.Reset.value]
    allowed_button_ids = {
        "paused": [InputIds.Play.value, InputIds.Reset.value],
        "running": [InputIds.Pause.value, InputIds.Reset.value],
        "over": [InputIds.Reset.value],
    }[game.state]

    for button_id in all_button_ids:
        button = inputs.itemById(button_id)
        button.isEnabled = button_id in allowed_button_ids
        button.value = False

    inputs.itemById(InputIds.BlockSize.value).isEnabled = game.state != "running"

    if event_args.input.id == InputIds.BlockSize.value:
        execution_queue.put(game.world.clear)
        game.world.grid_size = event_args.input.value
        faf.utils.set_camera(
            plane=game.plane,
            horizontal_borders=(
                -screen_offsets["left"] * game.world.grid_size,
                (game.width + screen_offsets["right"]) * game.world.grid_size,
            ),
            vertical_borders=(
                -screen_offsets["botton"] * game.world.grid_size,
                (game.height + screen_offsets["top"]) * game.world.grid_size,
            ),
        )

    if event_args.input.id == InputIds.SpeedSlider.value:
        game.speed = level_to_time_delta(event_args.input.valueOne)

    execution_queue.put(game.update_world)

    command.doExecute(False)


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

    # configuring commadn dialog buttons
    command.isOKButtonVisible = False
    command.cancelButtonText = "Exit"

    inputs = event_args.command.commandInputs

    controls_group = inputs.addGroupCommandInput(
        InputIds.ControlsGroup.value, "Controls"
    )
    play_button = controls_group.children.addBoolValueInput(
        InputIds.Play.value,
        "Play",
        True,
        str(Path(__file__).parent / "resources" / "play_button"),
        False,
    )
    play_button.tooltip = "Start/Continue the game."
    pause_button = controls_group.children.addBoolValueInput(
        InputIds.Pause.value,
        "Pause",
        True,
        str(Path(__file__).parent / "resources" / "pause_button"),
        False,
    )
    pause_button.tooltip = "Pause the game."
    reset_button = controls_group.children.addBoolValueInput(
        InputIds.Reset.value,
        "Reset",
        True,
        str(Path(__file__).parent / "resources" / "redo_button"),
        False,
    )
    reset_button.tooltip = "Reset the game"

    settings_group = inputs.addGroupCommandInput(
        InputIds.SettingsGroup.value, "Settings"
    )
    block_size_input = settings_group.children.addValueInput(
        InputIds.BlockSize.value,
        "Block size",
        "mm",
        adsk.core.ValueInput.createByReal(initial_block_size),
    )
    block_size_input.tooltip = "Side length of single block/voxel."
    keep_blocks_input = settings_group.children.addBoolValueInput(
        InputIds.KeepBodies.value, "Keep blocks", True, "", True
    )
    keep_blocks_input.tooltip = (
        "Determines if the blocks will be kept after leaving the game."
    )
    settings_group.isExpanded = False
    speed_slider = settings_group.children.addIntegerSliderListCommandInput(
        InputIds.SpeedSlider.value,
        "Speed",
        list(range(n_speed_levels)),
        False,
    )
    speed_slider.setText("slow", "fast")
    speed_slider.valueOne = initial_speed_level

    highscores_group = inputs.addGroupCommandInput(
        InputIds.HighscoresGroup.value, "Highscores"
    )
    highscores_group.children.addTextBoxCommandInput(
        InputIds.HighscoresHeading.value, "Rank", "Points", 1, True
    )

    scores = faf.utils.get_json_from_file(scores_path, [])
    for rank in range(n_scores_displayed):
        highscores_group.children.addTextBoxCommandInput(
            InputIds.HighscoresHeading.value + str(rank),
            str(rank + 1),
            str(scores[rank]) if rank < len(scores) else "-",
            1,
            True,
        )
    highscores_group.isExpanded = False

    # set up the game and world instacen
    comp = faf.utils.new_comp("snacade")
    design.rootComponent.allOccurrencesByComponent(comp).item(0).activate()
    world = vox.VoxelWorld(initial_block_size, comp)
    global game
    game = Game(
        world,
        Game.start_config_a,
        level_to_time_delta(initial_speed_level),
        mover_event_id,
    )

    # set the camera
    faf.utils.set_camera(
        plane=game.plane,
        horizontal_borders=(
            -screen_offsets["left"] * world.grid_size,
            (game.width + screen_offsets["right"]) * world.grid_size,
        ),
        vertical_borders=(
            -screen_offsets["botton"] * world.grid_size,
            (game.height + screen_offsets["top"]) * world.grid_size,
        ),
    )

    # does not work because command hasnt been created yet
    # event_args.command.doExecute(False)
    # but updating world / creating bodies works in creaed handler (but not in keyDown handler)
    progress_dialog = adsk.core.Application.get().userInterface.createProgressDialog()
    progress_dialog.message = "Building the world (%p%)"
    progress_dialog.title = "Building the world"
    game.update_world(progress_dialog)


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
        game.world.clear()


def on_periodic_move(event_args: adsk.core.CustomEventArgs):
    game.move_snake()
    # game.update_world() # --> somehow ont working --> therfore:
    # command cant be retrieved from args --> global instance necessary
    if command.isValid:
        execution_queue.put(game.update_world)
        command.doExecute(False)
    # results in fusion work --> must be executed from custom event handler


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
        panel = faf.Panel(tab)
        control = faf.Control(panel)
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