import adsk.core, adsk.fusion, adsk.cam, traceback


class Snake:
    _allowed_moves = ["left", "right", "up", "down"]

    def __init__(self, head, orientation, body_length):
        self._current_direction = orientation
        self._elements = [head] + [
            self._move_coordinate(head, self._current_direction, -i)
            for i in range(1, body_length)
        ]

        self._last_tail = None
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

    def eat(self):
        if self._last_tail is None:
            return False
        self._elements.append(self._last_tail)
        self._last_tail = None
        return self._elements[-1]

    def move(self):
        self._elements = [
            self._move_coordinate(self.head, self._current_direction)
        ] + self.body[:-1]

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
    maze_a = {(1, 1), (2, 2)}

    maze_voxel_style = (DirectCube, None, None)
    snake_body_voxel_style = (DirectSphere, None, None)
    snake_head_voxel_style = (DirectSphere, None, None)

    def __init__(self, maze, start_head, start_length, start_direction, n_foods):
        self._maze = maze
        self._snake = Snake(start_head, start_direction, start_length)
        self._foods = {}
        for _ in n_foods:
            self._create_food()

    def _food_coord(self):
        return random.

    def _update_world(self):
        self._world.update(
            {c: self.maze_voxel_style for c in self._maze}
            + {c: self.snake_body_voxel_style for c in self._snake.body}
            + {self._snake.head: self.snake_head_voxel_style}
        )

    def move_snake(self):
        self._snake.move()
        if self._snake.head in self._maze() or self._snake.head in self._snake.body:
            # Game over
            
        if self._snake.head in self._foods:
            self._snake.eat()
            self.foods.

        self._update_world()

    def left(self):
        self._snake.set_direction("left")

    def right(self):
        pass

    def up(self):
        pass

    def down(self):
        pass

    def play(self):
        pass

    def pause(self):
        pass

    def reset(self):
        pass


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        ui.messageBox("Hello addin")

    except:
        if ui:
            ui.messageBox("Failed:\n{}".format(traceback.format_exc()))


def stop(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        ui.messageBox("Stop addin")

    except:
        if ui:
            ui.messageBox("Failed:\n{}".format(traceback.format_exc()))
