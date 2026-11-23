from wxfilehelper.updates import version_key, select_update
from wxfilehelper import REPOSITORY


def release(tag, **kwargs):
    return {"tag_name": tag, "html_url": REPOSITORY + "/releases/tag/" + tag, **kwargs}


def test_semantic_version_sorting():
    assert version_key("v0.10.0") > version_key("0.9.9")
    assert version_key("1.0.0") > version_key("1.0.0-rc.9") > version_key("1.0.0-beta.9")


def test_beta_gets_newer_preview_and_stable_does_not():
    data = [release("v0.2.0-beta.1", prerelease=True)]
    assert select_update(data, "0.1.0-beta.1").version == "v0.2.0-beta.1"
    assert select_update(data, "0.1.0") is None


def test_drafts_old_versions_and_untrusted_links_are_ignored():
    data = [release("v0.1.0"), release("v0.3.0", draft=True),
            {**release("v0.4.0"), "html_url": "https://evil.test/installer"},
            release("not-a-version")]
    assert select_update(data, "0.2.0") is None


def test_highest_version_wins_regardless_of_publish_order():
    assert select_update([release("v1.2.0"), release("v1.1.0")], "0.1.0").version == "v1.2.0"
