import unittest
from pathlib import Path

from core.pipeline import (
    ML_MODEL_PATH,
    _extract_features,
    _feature_frame,
    load_ml_router,
    predict_llm,
)


class _FixedLabelModel:
    def __init__(self, label):
        self.label = label
        self.calls = 0

    def predict(self, frame):
        self.calls += 1
        return _ScalarResult(self.label)


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value


class MlRouterTests(unittest.TestCase):
    def test_default_model_path_is_project_relative_and_exists(self):
        self.assertTrue(Path(ML_MODEL_PATH).is_absolute())
        self.assertTrue(Path(ML_MODEL_PATH).is_file())

    def test_live_features_match_saved_model_contract(self):
        model, feature_cols = load_ml_router()

        self.assertIsNotNone(model)
        self.assertTrue(feature_cols)
        frame = _feature_frame("BEGIN DBMS_OUTPUT.PUT_LINE('x'); END;", feature_cols)
        self.assertEqual(list(frame.columns), list(feature_cols))
        self.assertEqual(frame.shape, (1, len(feature_cols)))

    def test_human_review_feature_uses_training_name(self):
        features = _extract_features("BEGIN DBMS_OUTPUT.PUT_LINE('x'); END;")

        self.assertIn("human_review_pattern_count", features)
        self.assertNotIn("gpt_pattern_count", features)
        self.assertGreater(features["human_review_pattern_count"], 0)

    def test_prediction_uses_model_instead_of_regex_fallback(self):
        model = _FixedLabelModel(label=3)
        route = predict_llm(
            "SELECT 1 FROM dual",
            model,
            ["human_review_pattern_count"],
        )

        self.assertEqual(route, "gemini")
        self.assertEqual(model.calls, 1)

    def test_old_gpt_feature_name_remains_compatible(self):
        frame = _feature_frame(
            "BEGIN DBMS_OUTPUT.PUT_LINE('x'); END;",
            ["gpt_pattern_count"],
        )

        self.assertGreater(frame.at[0, "gpt_pattern_count"], 0)


if __name__ == "__main__":
    unittest.main()
