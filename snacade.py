import traceback
import logging

import adsk.core, adsk.fusion, adsk.cam

from .fusion_addin_framework import fusion_addin_framework as faf
from .voxler import voxler as vox


class Snake:
    _allowed_moves = ["left", "right", "up", "down"]

    def __init__(self, head, orientation, body_length):
        self._current_direction = orientation
        self._elements = [head]
        # + [
        #     self._move_coordinate(head, self._current_direction, -i)
        #     for i in range(1, body_length)
        # ]

        # self._last_tail = None
        # self._move_coordinate(head, self._current_direction, -body_length - 1)

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

    # def eat(self):
    #     if self._last_tail is None:
    #         return False
    #     self._elements.append(self._last_tail)
    #     self._last_tail = None
    #     return self._elements[-1]

    def move(self):
        self._elements = [self._move_coordinate(self.head, self._current_direction)]
        # + self.body[:-1]

    def set_direction(self, new_direction):
        if new_direction not in self._allowed_moves:
            raise ValueError()
        self._current_direction = new_direction

    @property
    def head(self):
        return self._elements[0]

    @property
    def body(self):
        return self._elements[1:]


class Game:
    maze_a = {(1, 5), (2, 5), (3, 5)}

    start_config_a = {
        "maze": maze_a,
        "snake_head": (0, 0),
        "snake_direction": "up",
        "snake_length": 4,
    }

    maze_voxel_style = {
        "voxel_class": vox.DirectCube,
        "color": None,
        "appearance": "Steel - Satin",
    }
    snake_body_voxel_style = {
        "voxel_class": vox.DirectSphere,
        "color": None,
        "appearance": "Steel - Satin",
    }
    snake_head_voxel_style = {
        "voxel_class": vox.DirectSphere,
        "color": (255, 0, 0, 255),
        "appearance": "Steel - Satin",
    }

    def __init__(self, world, start_config, n_foods):
        self._world = world

        self._maze = start_config["maze"]
        self._snake = Snake(
            start_config["snake_head"],
            start_config["snake_direction"],
            start_config["snake_length"],
        )
        self._foods = {}
        # for _ in n_foods:
        #     self._create_food()

    def _create_food(self):
        pass
        # self._foods.append(random.)

    def update_world(self):
        self._world.update(
            {
                **{(*c, 0): self.maze_voxel_style for c in self._maze},
                # **{(*c, 0): self.snake_body_voxel_style for c in self._snake.body},
                **{(*self._snake.head, 0): self.snake_head_voxel_style},
            }
        )

        # def move_snake(self):
        #     self._snake.move()
        # if self._snake.head in self._maze or self._snake.head in self._snake.body:
        # Game over
        # pass

        # if self._snake.head in self._foods:
        #     self._snake.eat()
        # self.foods.

    def left(self):
        self._snake.set_direction("left")
        # self.move_snake()
        self._snake.move()

    def right(self):
        self._snake.set_direction("right")
        # self.move_snake()
        self._snake.move()

    def up(self):
        self._snake.set_direction("up")
        # self.move_snake()
        self._snake.move()

    def down(self):
        self._snake.set_direction("down")
        # self.move_snake()
        self._snake.move()

    def play(self):
        pass

    def pause(self):
        pass

    def reset(self):
        pass


addin = None
game = None
comp = None


def on_execute(event_args):
    game.update_world()


def on_input_changed(event_args):
    pass


def on_created(event_args: adsk.core.CommandCreatedEventArgs):
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

    event_args.command.commandInputs.addBoolValueInput("boolInputId", "my input", True)

    global game
    game = Game(
        vox.VoxelWorld(1, faf.utils.new_comp("snacade")), Game.start_config_a, 10
    )

    event_args.command.doExecute(False)


def on_key_down(event_args: adsk.core.KeyboardEventArgs):
    {
        adsk.core.KeyCodes.UpKeyCode: game.up,
        adsk.core.KeyCodes.LeftKeyCode: game.left,
        adsk.core.KeyCodes.RightKeyCode: game.right,
        adsk.core.KeyCodes.DownKeyCode: game.down,
    }.get(event_args.keyCode, lambda: None)()

    event_args.firingEvent.sender.doExecute(False)


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
        command = faf.AddinCommand(
            control,
            name="snacade",
            commandCreated=on_created,
            inputChanged=on_input_changed,
            keyDown=on_key_down,
            execute=on_execute,
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