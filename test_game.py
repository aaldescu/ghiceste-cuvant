"""Teste pentru motorul jocului, fără Jev: distribuțiile lui Jev sunt simulate."""

import unittest

import game
from game import MAX_GUESSES, NONE, next_turn


class NextTurnTest(unittest.TestCase):
    def test_always_tries_a_word(self):
        turn = next_turn({"pisică": 0.1, "câine": 0.08, NONE: 0.82}, [])
        self.assertEqual(turn["kind"], "guess")
        self.assertEqual(turn["guess"], "pisică")

    def test_message_depends_on_confidence(self):
        self.assertIn("Te gândești", next_turn({"pisică": 0.9, NONE: 0.1}, [])["message"])
        self.assertIn("E cumva", next_turn({"pisică": 0.5, NONE: 0.5}, [])["message"])
        self.assertIn("Poate", next_turn({"pisică": 0.1, NONE: 0.9}, [])["message"])

    def test_never_guesses_none_or_rejected(self):
        turn = next_turn({NONE: 0.8, "pisică": 0.15, "câine": 0.05}, ["pisică"])
        self.assertEqual(turn["guess"], "câine")

    def test_remembers_second_candidate(self):
        turn = next_turn({"reparare": 0.72, "reparație": 0.2, NONE: 0.08}, [])
        self.assertEqual(turn["guess"], "reparare")
        self.assertEqual(turn["next_guess"], "reparație")

    def test_tries_second_candidate_after_no(self):
        turn = next_turn({"restaurare": 0.3, "reparație": 0.19, NONE: 0.51}, ["reparare"],
                         after_wrong_guess=True, next_guess="reparație")
        self.assertEqual(turn["guess"], "reparație")
        self.assertEqual(turn["message"], "Atunci „reparație”?")

    def test_new_direction_beats_second_candidate(self):
        # „cocină” era al doilea după „cameră”, dar indiciul nou („e în bucătărie”) arată spre altceva.
        turn = next_turn({"oală": 0.4, "cocină": 0.05, NONE: 0.55}, ["cameră"], after_wrong_guess=True, next_guess="cocină")
        self.assertEqual(turn["guess"], "oală")

    def test_clear_new_clue_beats_second_candidate(self):
        turn = next_turn({"pisică": 0.95, NONE: 0.05}, ["câine"], after_wrong_guess=True, next_guess="lup")
        self.assertEqual(turn["guess"], "pisică")

    def test_gives_up_after_too_many_wrong_guesses(self):
        rejected = [f"w{i}" for i in range(MAX_GUESSES)]
        self.assertEqual(next_turn({"pisică": 0.9, NONE: 0.1}, rejected)["kind"], "giveup")

    def test_says_word_is_unknown_when_nothing_fits(self):
        turn = next_turn({"pisică": 0.3, NONE: 0.7}, ["pisică"])
        self.assertEqual(turn["kind"], "giveup")
        self.assertEqual(turn["message"], game.UNKNOWN_WORD)


def judgment(e_indiciu=0.9, adevarat=0.9, util=0.8, spune_cuvantul=0.05):
    return {"e_indiciu": e_indiciu, "adevarat": adevarat, "util": util, "spune_cuvantul": spune_cuvantul}


class JudgeTest(unittest.TestCase):
    def test_true_and_useful_clue_is_valid(self):
        self.assertEqual(game.judge_clue(judgment()), "valid")

    def test_false_clue_is_a_lie(self):
        # „Zboară.” pentru tigaie: Jev nu e sigur că e un indiciu, dar e clar fals.
        self.assertEqual(game.judge_clue(judgment(e_indiciu=0.42, adevarat=0.03)), "minciuna")

    def test_reaction_is_not_judged(self):
        # „hmm” nu e adevărat, dar nici minciună: nu e indiciu.
        self.assertEqual(game.judge_clue(judgment(e_indiciu=0.02, adevarat=0.26, util=0.03)), "nu_e_indiciu")

    def test_general_clue_is_vague(self):
        self.assertEqual(game.judge_clue(judgment(util=0.04)), "vag")

    def test_uncertain_truth_is_doubtful(self):
        self.assertEqual(game.judge_clue(judgment(adevarat=0.35)), "indoielnic")

    def test_saying_the_word_is_caught_first(self):
        self.assertEqual(game.judge_clue(judgment(spune_cuvantul=0.88)), "spune_cuvantul")

    def test_score_counts_valid_clues_and_escape_bonus(self):
        verdicts = ["valid", "vag", "valid", "nu_e_indiciu", "indoielnic"]
        self.assertEqual(game.score_round(verdicts, escaped=False)["score"], 2)
        self.assertEqual(game.score_round(verdicts, escaped=True)["score"], 2 + game.ESCAPE_BONUS)

    def test_one_lie_disqualifies(self):
        result = game.score_round(["valid", "valid", "minciuna"], escaped=True)
        self.assertEqual((result["score"], result["disqualified"], result["reason"]), (0, True, "minciuna"))

    def test_no_to_the_right_guess_disqualifies(self):
        result = game.score_round(["valid", "valid"], escaped=True, lied_on_guess="tigaie")
        self.assertEqual((result["score"], result["disqualified"]), (0, True))
        self.assertEqual(result["lied_on"], "tigaie")

    def test_unknown_word_gets_no_points(self):
        result = game.score_round(["valid", "valid"], escaped=True, known_word=False)
        self.assertEqual((result["score"], result["disqualified"], result["reason"]), (0, False, "cuvant_necunoscut"))


class GraphTest(unittest.TestCase):
    def setUp(self):
        categories = {c: {"grup": "g", "descriere": c} for c in ("a", "b", "c")}
        links = {f"a{i}": {"a": 1.0} for i in range(200)}
        links.update({f"b{i}": {"b": 1.0} for i in range(100)})
        links.update({f"c{i}": {"c": 1.0} for i in range(30)})
        links["ab"] = {"a": 0.6, "b": 0.4}
        self.graph = game.Graph(links, categories)

    def test_word_can_have_several_parents(self):
        self.assertIn("ab", self.graph.members["a"])
        self.assertIn("ab", self.graph.members["b"])

    def test_selection_fits_in_one_question(self):
        words, _ = self.graph.select_words({"a": 0.5, "b": 0.3, "c": 0.2})
        self.assertLessEqual(len(words), game.MAX_WORDS)
        self.assertEqual(len(words), len(set(words)))

    def test_skips_category_that_does_not_fit(self):
        # „b" nu mai încape după „a", dar „c" da; acoperirea numără doar ce am luat.
        words, coverage = self.graph.select_words({"a": 0.5, "b": 0.3, "c": 0.2})
        self.assertIn("c0", words)
        self.assertNotIn("b0", words)
        self.assertAlmostEqual(coverage, 0.7)

    def test_stops_when_mass_is_covered(self):
        words, coverage = self.graph.select_words({"c": 0.96, "a": 0.04})
        self.assertEqual(len(words), 30)
        self.assertAlmostEqual(coverage, 0.96)

    def test_excluded_words_are_left_out(self):
        words, _ = self.graph.select_words({"c": 1.0}, excluded={"c0"})
        self.assertNotIn("c0", words)


class DataTest(unittest.TestCase):
    def test_real_graph_fits_jev_limits(self):
        graph = game.Graph.load()
        self.assertLessEqual(len(graph.categories), game.MAX_OPTIONS)
        for cid, members in graph.members.items():
            self.assertLessEqual(len(members), game.MAX_WORDS, cid)
        self.assertNotIn(NONE, graph.words)
        self.assertEqual(set(graph.words), set(game.load_words()))


if __name__ == "__main__":
    unittest.main()
