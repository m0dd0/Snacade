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


### HELPER FUNCTIONS ###
def level_to_time_delta(level):
    delta_time = (max_wait_time - min_wait_time) / (n_speed_levels - 1)
    return max_wait_time - level * delta_time


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


def zigzag_obstacle_generator(height, width, n_zigzags, zizag_portion, vertical=True):
    obstacles = set()
    if vertical:
        d = int(width / (n_zigzags + 1))
        up = True
        for i in range(n_zigzags):
            x = int(d + i * d)
            for y in range(0, int(height * zizag_portion)):
                if up:
                    obstacles.add((x, y))
                else:
                    obstacles.add((x, height - 1 - y))
            up = not up
    else:
        d = int(height / (n_zigzags + 1))
        up = True
        for i in range(n_zigzags):
            y = int(d + i * d)
            for x in range(0, int(width * zizag_portion)):
                if up:
                    obstacles.add((x, y))
                else:
                    obstacles.add((width - 1 - x, y))
            up = not up

    return obstacles


def random_obstacle_generator(height, width, n_obstacles, snake_head):
    obstacles = set()
    while len(obstacles) < n_obstacles:
        new_obst = (random.randint(0, width), random.randint(0, height))
        if abs(snake_head[0] - new_obst[0]) > 5 and abs(snake_head[1] - new_obst[1]):
            obstacles.add(new_obst)
    return obstacles


### GAME LOGIC ###
class Snake:
    _allowed_moves = ["left", "right", "up", "down"]

    def __init__(self, head, orientation, body_length, portals=None):
        self._current_direction = orientation
        self._elements = [head] + [
            self._move_coordinate(head, self._current_direction, -i)
            for i in range(1, body_length)
        ]

        self._last_tail = None
        self._direction_setable = True

        self._portals = portals

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
        new_head = self._move_coordinate(self._elements[0], self._current_direction)
        if self._portals is not None:
            new_head = (new_head[0] % self._portals[0], new_head[1] % self._portals[1])
        self._elements.insert(0, new_head)
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
    start_configs = {
        "standard": {
            "portal": True,
            "height": 25,
            "width": 50,
            "obstacles": set(),
            "snake_head": (27, 12),
            "snake_direction": "right",
            "snake_length": 5,
        },
        "frame": {
            "portal": False,
            "height": 25,
            "width": 50,
            "obstacles": set(),
            "snake_head": (27, 12),
            "snake_direction": "right",
            "snake_length": 5,
        },
        "zigzag": {
            "portal": False,
            "height": 25,
            "width": 50,
            "obstacles": zigzag_obstacle_generator(25, 50, 3, 0.7),
            "snake_head": (5, 10),
            "snake_direction": "up",
            "snake_length": 5,
        },
        "zigzag horizontal": {
            "portal": False,
            "height": 25,
            "width": 50,
            "obstacles": zigzag_obstacle_generator(25, 50, 3, 0.7, vertical=False),
            "snake_head": (10, 22),
            "snake_direction": "right",
            "snake_length": 5,
        },
        "random obstacles": {
            "portal": True,
            "height": 25,
            "width": 50,
            "obstacles": random_obstacle_generator(25, 50, 35, (5, 10)),
            "snake_head": (5, 10),
            "snake_direction": "up",
            "snake_length": 5,
        },
        "random obstacles frame": {
            "portal": False,
            "height": 25,
            "width": 50,
            "obstacles": random_obstacle_generator(25, 50, 35, (5, 10)),
            "snake_head": (5, 10),
            "snake_direction": "up",
            "snake_length": 5,
        },
    }

    maze_voxel_style = {
        "voxel_class": vox.DirectCube,
        "color": None,
        "appearance": "Steel - Satin",
        "name": "maze voxel",
    }
    portal_voxel_style = {
        "voxel_class": vox.DirectCube,
        "color": (0, 0, 255, 255),
        "appearance": "Steel - Satin",
        "name": "maze voxel",
    }
    snake_body_voxel_style = {
        "voxel_class": vox.DirectSphere,
        "color": (0, 255, 0, 255),
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
        "color": (255, 255, 0, 255),
        "appearance": "Steel - Satin",
        "name": "food voxel",
    }

    def __init__(self, world, start_config, speed, mover_event_id):
        self.world = world

        self._speed = speed

        self._mover_thread = faf.utils.PeriodicExecuter(
            speed, lambda: adsk.core.Application.get().fireCustomEvent(mover_event_id)
        )

        self._state = "start"

        self._score = None
        self._height = None
        self._width = None
        self._plane = None
        self._maze = None
        self._portal = None
        self._possible_food_positions = None
        self._snake = None
        self._food = None

        self._start_config = start_config
        self.build_start_state()

    def build_start_state(self):
        if self._state != "start":
            return

        self._score = 0

        self._height = self._start_config["height"]
        self._width = self._start_config["width"]

        self._plane = "xy"  # TODO setable

        self._maze = set().union(
            self._start_config["obstacles"],
        )
        self._portal = set()

        borders = set().union(
            {(i, -1) for i in range(-1, self._width + 1)},
            {(i, self._height) for i in range(-1, self._width + 1)},
            {(-1, j) for j in range(-1, self._height + 1)},
            {(self._width, j) for j in range(-1, self._height + 1)},
        )
        # (-1,-1) -> (width,0)
        # (-1,height) -> (width, height)
        # (-1,-1) -> (-1,height)
        # (width,-1) -> (width,height)

        if self._start_config["portal"]:
            self._portal = self._portal.union(borders)
        else:
            self._maze = self._maze.union(borders)

        # use list to enable the use of random.choice
        self._possible_food_positions = {
            (i, j) for i in range(0, self._width) for j in range(0, self._height)
        } - self._start_config["obstacles"]

        self._snake = Snake(
            self._start_config["snake_head"],
            self._start_config["snake_direction"],
            self._start_config["snake_length"],
            portals=(self._width, self._height)
            if self._start_config["portal"]
            else None,
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
        if self._state != "running":
            return
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

            msg = f"GAME OVER\n\nYour snake ate {self._score} snacks."
            if achieved_rank < n_scores_displayed:
                msg += f"\n\nCongratulations, you made the {faf.utils.make_ordinal(achieved_rank+1)} place in the ranking!"
                for rank in range(n_scores_displayed):
                    command.commandInputs.itemById(
                        InputIds.HighscoresHeading.value + str(rank)
                    ).text = str(scores[rank] if rank < len(scores) else "-")
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
                **{(*c, 0): self.portal_voxel_style for c in self._portal},
            },
            *args,
            **kwargs,
        )

    def left(self):
        if self._state == "running":
            self._snake.set_direction("left")

    def right(self):
        if self._state == "running":
            self._snake.set_direction("right")

    def up(self):
        if self._state == "running":
            self._snake.set_direction("up")

    def down(self):
        if self._state == "running":
            self._snake.set_direction("down")

    def play(self):
        if self._state in ("paused", "start"):
            self._mover_thread.start()
            self._state = "running"

    def pause(self):
        if self._state == "running":
            self._mover_thread.pause()
            self._state = "paused"

    def reset(self):
        if self._state in ("running", "paused", "over", "start"):
            self._mover_thread.reset()
            self._mover_thread.pause()
            self._state = "start"
            self.build_start_state()

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

    @property
    def start_config(self):
        return self._start_config.copy()

    @start_config.setter
    def start_config(self, new_start_config):
        self._start_config = new_start_config


### INTER HANDLER SHARED VARIABLES ###
# varibale which are created in an event handler and need to be accessed from
# different event handler(s) as well
addin = None
game = None
comp = None
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
    MazeDropdown = auto()


### HANDLERS ###
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
        "start": [InputIds.Play.value, InputIds.Reset.value],
    }[game.state]

    for button_id in all_button_ids:
        button = inputs.itemById(button_id)
        button.isEnabled = button_id in allowed_button_ids
        button.value = False

    inputs.itemById(InputIds.BlockSize.value).isEnabled = game.state != "running"

    if event_args.input.id == InputIds.BlockSize.value:
        execution_queue.put(game.world.clear)
        game.world.grid_size = event_args.input.value
        set_camera(game)

    if event_args.input.id == InputIds.SpeedSlider.value:
        game.speed = level_to_time_delta(event_args.input.valueOne)

    inputs.itemById(InputIds.MazeDropdown.value).isEnabled = game.state == "start"

    if event_args.input.id == InputIds.MazeDropdown.value:
        game.start_config = Game.start_configs[event_args.input.selectedItem.name]
        game.build_start_state()

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

    settings_group = inputs.addGroupCommandInput(
        InputIds.SettingsGroup.value, "Settings"
    )
    maze_dropdown = settings_group.children.addDropDownCommandInput(
        InputIds.MazeDropdown.value,
        "World",
        adsk.core.DropDownStyles.TextListDropDownStyle,
    )
    for maze_name in Game.start_configs.keys():
        maze_dropdown.listItems.add(maze_name, False)
    maze_dropdown.listItems.item(0).isSelected = True
    initial_maze = maze_dropdown.listItems.item(0).name

    speed_slider = settings_group.children.addIntegerSliderListCommandInput(
        InputIds.SpeedSlider.value,
        "Speed",
        list(range(n_speed_levels)),
        False,
    )
    speed_slider.setText("slow", "fast")
    speed_slider.valueOne = initial_speed_level
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
    # settings_group.isExpanded = False

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
    pause_button.isEnabled = False
    reset_button = controls_group.children.addBoolValueInput(
        InputIds.Reset.value,
        "Reset",
        True,
        str(Path(__file__).parent / "resources" / "redo_button"),
        False,
    )
    reset_button.tooltip = "Reset the game"

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
    global comp
    comp = faf.utils.new_comp("snacade")
    design.rootComponent.allOccurrencesByComponent(comp).item(0).activate()
    world = vox.VoxelWorld(initial_block_size, comp, offset=(1.5, 1.5))
    global game
    game = Game(
        world,
        Game.start_configs[initial_maze],
        level_to_time_delta(initial_speed_level),
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