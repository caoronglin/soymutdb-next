from app.core.features import FEATURES, parse_feature_value


def test_registered_features_have_stable_defaults_and_public_visibility():
    assert "imports.module_tsv" in FEATURES
    assert "imports.module_xlsx" in FEATURES
    assert FEATURES["mcp.write_tools"].default is False
    assert FEATURES["publication.github_pages"].public is False


def test_feature_values_fail_safe_to_default():
    assert parse_feature_value("true", False) is True
    assert parse_feature_value("off", True) is False
    assert parse_feature_value("unexpected", True) is True
    assert parse_feature_value(None, False) is False
