"""Teste pentru motorul jocului, fără Jev: o bază de cunoștințe sintetică și jucători simulați."""

import random
import unittest

from game import MAX_GUESSES, Game


def synthetic_game(n_words=150, n_questions=50, seed=1):
    rng = random.Random(seed)
    questions = [{"id": f"q{i}", "text": f"Întrebarea {i}?"} for i in range(n_questions)]
    kb = {f"w{j}": {q["id"]: rng.choice([0.02, 0.1, 0.5, 0.9, 0.98]) for q in questions} for j in range(n_words)}
    return Game(kb, questions), kb


def play(game, kb, secret, rng, mistake_rate=0.0):
    """Joacă o partidă cu un jucător care se gândește la `secret`. Întoarce (ghicit, nr_întrebări)."""
    answers, rejected = [], []
    for _ in range(100):
        turn = game.next_turn(answers, rejected)
        if turn["kind"] == "giveup":
            return False, len(answers)
        if turn["kind"] == "guess":
            if turn["guess"] == secret:
                return True, len(answers)
            rejected.append(turn["guess"])
            continue
        y = 1.0 if kb[secret][turn["question_id"]] >= 0.5 else 0.0
        if kb[secret][turn["question_id"]] == 0.5:
            y = 0.5
        if rng.random() < mistake_rate:
            y = 1 - y
        answers.append((turn["question_id"], y))
    return False, len(answers)


class GameTest(unittest.TestCase):
    def test_first_turn_is_a_question(self):
        game, _ = synthetic_game()
        turn = game.next_turn([])
        self.assertEqual(turn["kind"], "question")
        self.assertIn(turn["question_id"], game.questions)

    def test_never_repeats_a_question(self):
        game, kb = synthetic_game()
        answers = []
        for _ in range(20):
            turn = game.next_turn(answers)
            if turn["kind"] != "question":
                break
            self.assertNotIn(turn["question_id"], {q for q, _ in answers})
            answers.append((turn["question_id"], 1.0))

    def test_guesses_most_words_with_honest_player(self):
        game, kb = synthetic_game()
        rng = random.Random(2)
        results = [play(game, kb, w, rng) for w in game.words]
        wins = sum(won for won, _ in results)
        self.assertGreater(wins / len(results), 0.95)

    def test_survives_some_wrong_answers(self):
        game, kb = synthetic_game()
        rng = random.Random(3)
        results = [play(game, kb, w, rng, mistake_rate=0.05) for w in game.words]
        wins = sum(won for won, _ in results)
        self.assertGreater(wins / len(results), 0.8)

    def test_dont_know_gives_no_information(self):
        game, _ = synthetic_game()
        before = game.posterior([])
        after = game.posterior([("q0", 0.5)])
        for w in before:
            self.assertAlmostEqual(before[w], after[w])

    def test_gives_up_after_too_many_wrong_guesses(self):
        game, _ = synthetic_game()
        turn = game.next_turn([], rejected=game.words[:MAX_GUESSES])
        self.assertEqual(turn["kind"], "giveup")


if __name__ == "__main__":
    unittest.main()
