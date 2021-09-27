import random

import adsk.core, adsk.fusion, adsk.cam

from .voxler import voxler as vox
from .fusion_addin_framework import fusion_addin_framework as faf


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


def level_to_time_delta(level):
    delta_time = (max_wait_time - min_wait_time) / (n_speed_levels - 1)
    return max_wait_time - level * delta_time


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
        "additional_properties": {"name": "maze voxel"},
    }
    portal_voxel_style = {
        "voxel_class": vox.DirectCube,
        "color": (0, 0, 255, 255),
        "appearance": "Steel - Satin",
        "additional_properties": {"name": "maze voxel"},
    }
    snake_body_voxel_style = {
        "voxel_class": vox.DirectSphere,
        "color": (0, 255, 0, 255),
        "appearance": "Steel - Satin",
        "additional_properties": {"name": "snake voxel"},
    }
    snake_head_voxel_style = {
        "voxel_class": vox.DirectSphere,
        "color": (255, 0, 0, 255),
        "appearance": "Steel - Satin",
        "additional_properties": {"name": "snake voxel"},
    }
    food_voxel_style = {
        "voxel_class": vox.DirectSphere,
        "color": (255, 255, 0, 255),
        "appearance": "Steel - Satin",
        "additional_properties": {"name": "food voxel"},
    }

    def __init__(self, world, game_ui, mover_event_id):
        self._world = world
        self._game_ui = game_ui

        # TODO rename speed -> move_time_delta
        self._speed = level_to_time_delta(self._game_ui.speedSlider.valueOne)

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

        self.build_start_state()

    def build_start_state(self):
        if self._state != "start":
            return

        start_config = self._game_ui.maze_dropdown.listItems.selectedItem.name

        self._score = 0

        self._height = start_config["height"]
        self._width = start_config["width"]

        self._plane = "xy"  # TODO setable

        self._maze = set().union(
            start_config["obstacles"],
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
        } - start_config["obstacles"]

        self._snake = Snake(
            start_config["snake_head"],
            start_config["snake_direction"],
            start_config["snake_length"],
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
            # TODO port to game ui class
            self._game_ui.game_over_state(self._score)
            # command.commandInputs.itemById(InputIds.Pause.value).isEnabled = False
            # command.commandInputs.itemById(InputIds.BlockSize.value).isEnabled = True

            # scores = faf.utils.get_json_from_file(str(scores_path), [])
            # achieved_rank = len(scores) - bisect.bisect_right(scores[::-1], self._score)
            # scores.insert(achieved_rank, self._score)
            # with open(scores_path, "w") as f:
            #     json.dump(scores, f, indent=4)

            # msg = f"GAME OVER\n\nYour snake ate {self._score} snacks."
            # if achieved_rank < n_scores_displayed:
            #     msg += f"\n\nCongratulations, you made the {faf.utils.make_ordinal(achieved_rank+1)} place in the ranking!"
            #     self.control_board.update_leaderboard()
            #     # for rank in range(n_scores_displayed):
            #     #     command.commandInputs.itemById(
            #     #         InputIds.HighscoresHeading.value + str(rank)
            #     #     ).text = str(scores[rank] if rank < len(scores) else "-")
            # adsk.core.Application.get().userInterface.messageBox(msg)

        if self._snake.head == self._food:
            self._snake.eat()
            self._food = self._find_food_position()
            self._score += 1
            self._game_ui.update_score()

    def update_world(self, *args, **kwargs):
        # TODO adapt for setable drawing plane
        self._world.update(
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
    def state(self):
        return self._state

    @state.setter
    def state(self, new_state):
        self._state = new_state
        self._game_ui.change_state(new_state, self)