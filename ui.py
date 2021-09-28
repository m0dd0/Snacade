from enum import auto
import json
import bisect
from pathlib import Path

import adsk.core, adsk.fusion, adsk.cam

from .fusion_addin_framework import fusion_addin_framework as faf

from game import Game


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
    def __init__(
        self,
        command,
        scores_path,
        n_scores_displayed,
        n_speed_levels,
        initial_speed_level,
        initial_block_size,
        no_score_symbol,
    ):
        self.command = command

        # TODO make attributes _protected
        self.scores_path = scores_path
        self.no_score_symbol = no_score_symbol
        self.n_scores_displayed = n_scores_displayed
        self.n_speed_levels = n_speed_levels
        self.initial_speed_level = initial_speed_level
        self.initial_block_size = initial_block_size

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
                list(range(self.n_speed_levels)),
                False,
            )
        )
        self.speed_slider.setText("slow", "fast")
        self.speed_slider.valueOne = self.initial_speed_level

        self.block_size_input = self.settings_group.children.addValueInput(
            InputIds.BlockSize.value,
            "Block size",
            "mm",
            adsk.core.ValueInput.createByReal(self.initial_block_size),
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

        # scores = faf.utils.get_json_from_file(scores_path, [])
        self.highscore_texts = [
            self.highscores_group.children.addTextBoxCommandInput(
                InputIds.HighscoresHeading.value + str(rank),
                str(rank + 1),
                self.no_score_symbol,
                1,
                True,
            )
            for rank in range(self.n_scores_displayed)
        ]
        self.update_leaderboard(None)
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

    def change_state(self, new_state):
        {
            "start": self.start_state,
            "paused": self.pause_state,
            "running": self.running_state,
            "over": self.game_over_state,
        }[new_state]()

    def update_leaderboad(self, score):
        scores = faf.utils.get_json_from_file(str(self.scores_path), [])
        if score is not None:
            achieved_rank = len(scores) - bisect.bisect_right(scores[::-1], score)
            scores.insert(achieved_rank, score)
            with open(self.scores_path, "w") as f:
                json.dump(scores, f, indent=4)

        msg = f"GAME OVER\n\nYour snake ate {score} snacks."
        if achieved_rank < self.n_scores_displayed:
            msg += f"\n\nCongratulations, you made the {faf.utils.make_ordinal(achieved_rank+1)} place in the ranking!"
            for rank in range(self.n_scores_displayed):
                self.highscore_texts[rank].text = str(
                    scores[rank] if rank < len(scores) else self.no_score_symbol
                )

        adsk.core.Application.get().userInterface.messageBox(msg)
