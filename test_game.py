"""Teste pentru motorul jocului, fără Jev: distribuțiile lui Jev sunt simulate."""

import unittest

import game
from game import GUESS_THRESHOLD, MAX_GUESSES, MAX_MESSAGES, NONE, next_turn


class NextTurnTest(unittest.TestCase):
    def test_guesses_when_confident(self):
        turn = next_turn({"pisică": 0.9, "câine": 0.05, NONE: 0.05}, [], 1)
        self.assertEqual(turn["kind"], "guess")
        self.assertEqual(turn["guess"], "pisică")

    def test_asks_for_more_when_unsure(self):
        turn = next_turn({"pisică": 0.4, "câine": 0.35, NONE: 0.25}, [], 1)
        self.assertEqual(turn["kind"], "hint")
        self.assertEqual(turn["candidates"][:2], ["pisică", "câine"])

    def test_never_guesses_none(self):
        turn = next_turn({NONE: 0.95, "pisică": 0.05}, [], 1)
        self.assertEqual(turn["kind"], "hint")

    def test_skips_rejected_words_and_renormalizes(self):
        # Fără „pisică", „câine" are 0.45 / 0.5 = 0.9 și trece de prag.
        turn = next_turn({"pisică": 0.5, "câine": 0.45, NONE: 0.05}, ["pisică"], 2)
        self.assertEqual(turn["kind"], "guess")
        self.assertEqual(turn["guess"], "câine")
        self.assertGreaterEqual(turn["confidence"], GUESS_THRESHOLD)

    def test_guesses_anyway_after_many_messages(self):
        turn = next_turn({"pisică": 0.4, "câine": 0.3, NONE: 0.3}, [], MAX_MESSAGES)
        self.assertEqual(turn["kind"], "guess")
        self.assertEqual(turn["guess"], "pisică")

    def test_gives_up_when_word_is_unknown(self):
        turn = next_turn({NONE: 0.7, "pisică": 0.3}, [], MAX_MESSAGES)
        self.assertEqual(turn["kind"], "giveup")

    def test_gives_up_after_too_many_wrong_guesses(self):
        turn = next_turn({"pisică": 0.9, NONE: 0.1}, ["a", "b", "c", "d", "e"][:MAX_GUESSES], 3)
        self.assertEqual(turn["kind"], "giveup")

    def test_says_so_after_wrong_guess(self):
        turn = next_turn({"pisică": 0.4, NONE: 0.6}, ["câine"], 2, after_wrong_guess=True)
        self.assertEqual(turn["message"], game.AFTER_WRONG_GUESS)


class WordsTest(unittest.TestCase):
    def test_word_list_fits_in_one_choice(self):
        words = game.load_words()
        self.assertLessEqual(len(words), game.MAX_WORDS)
        self.assertEqual(len(words), len(set(words)))
        self.assertNotIn(NONE, words)


if __name__ == "__main__":
    unittest.main()
