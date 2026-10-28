"""New npm dependency gate (`scripts/check_new_npm_dependencies.py`)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import check_new_npm_dependencies as check

NOW = datetime(2026, 10, 28, tzinfo=UTC)


def _document(created: datetime | None, versions: int = 3) -> dict[str, Any]:
    time = {} if created is None else {"created": created.isoformat().replace("+00:00", "Z")}
    return {"time": time, "versions": {f"1.{i}.0": {} for i in range(versions)}}


def test_declared_packages_reads_every_dependency_section() -> None:
    manifest = {
        "name": "neuron-web",
        "dependencies": {"react": "19.3.1"},
        "devDependencies": {"@types/react": "19.3.0"},
        "optionalDependencies": {"fsevents": "2.3.3"},
        "peerDependencies": {"react-dom": "19.3.1"},
        "scripts": {"lint": "eslint ."},
    }

    assert check.declared_packages(manifest) == {
        "react",
        "@types/react",
        "fsevents",
        "react-dom",
    }


def test_unknown_package_is_refused_as_possibly_hallucinated() -> None:
    verdict = check.judge("reakt-dom", None, NOW, allow_young=False)

    assert not verdict.ok
    assert "hallucinated" in verdict.message


def test_young_package_is_refused_unless_a_human_approved_it() -> None:
    young = _document(NOW - timedelta(days=check.MIN_AGE_DAYS - 1))

    assert not check.judge("fresh", young, NOW, allow_young=False).ok
    assert check.judge("fresh", young, NOW, allow_young=True).ok


def test_package_at_the_age_limit_passes() -> None:
    assert check.judge("steady", _document(NOW - timedelta(days=check.MIN_AGE_DAYS)), NOW, False).ok


def test_document_without_a_creation_time_is_refused() -> None:
    assert not check.judge("odd", _document(None), NOW, allow_young=True).ok


@pytest.mark.parametrize("name", ["../etc/passwd", "Upper", "a b", "@scope", "react?x=1", ""])
def test_malformed_names_never_reach_the_registry(name: str) -> None:
    with pytest.raises(ValueError, match="not a valid npm package name"):
        check.fetch_metadata(name)


def test_a_missing_base_manifest_counts_as_empty(tmp_path: Path) -> None:
    head = tmp_path / "package.json"
    head.write_text(json.dumps({"dependencies": {"react": "19.3.1"}}), encoding="utf-8")

    assert check.declared_packages(check._load(str(tmp_path / "absent.json"))) == set()
    assert check.declared_packages(check._load(str(head))) == {"react"}


def test_no_added_packages_passes_without_network(tmp_path: Path) -> None:
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps({"dependencies": {"react": "19.3.1"}}), encoding="utf-8")

    assert check.main(["check", str(manifest), str(manifest)]) == 0


# --- lockfile integrity and transitive packages ---------------------------------------------

_INTEGRITY = "sha512-" + "A" * 86 + "=="


def _lock(**entries: dict[str, Any]) -> dict[str, Any]:
    return {"lockfileVersion": 3, "packages": {"": {"name": "neuron-web"}, **entries}}


def _entry(package: str, version: str = "1.2.3", **overrides: Any) -> dict[str, Any]:
    base = package.split("/")[-1]
    return {
        "version": version,
        "resolved": f"https://registry.npmjs.org/{package}/-/{base}-{version}.tgz",
        "integrity": _INTEGRITY,
        **overrides,
    }


def test_a_faithful_lockfile_has_no_violations() -> None:
    lock = _lock(
        **{
            "node_modules/react": _entry("react"),
            "node_modules/@types/react": _entry("@types/react"),
            "node_modules/a/node_modules/react": _entry("react", "18.0.0"),
        }
    )

    assert check.lockfile_violations(lock) == []


@pytest.mark.parametrize(
    "entry",
    [
        _entry("react", resolved="https://registry.npmjs.org/reakt/-/reakt-1.2.3.tgz"),
        _entry("react", resolved="https://registry.npmjs.org/react/-/react-9.9.9.tgz"),
        _entry("react", resolved="http://registry.npmjs.org/react/-/react-1.2.3.tgz"),
        _entry("react", resolved="https://evil.example/react/-/react-1.2.3.tgz"),
        _entry("react", resolved="https://registry.npmjs.org/react/-/react-1.2.3.tgz?x=1"),
        _entry("react", resolved="git+https://github.com/someone/react.git#abc"),
        _entry("react", integrity="sha1-AAAAAAAAAAAAAAAAAAAAAAAAAAA="),
        {k: v for k, v in _entry("react").items() if k != "integrity"},
        {k: v for k, v in _entry("react").items() if k != "resolved"},
    ],
)
def test_tampered_lockfile_entries_are_reported(entry: dict[str, Any]) -> None:
    assert check.lockfile_violations(_lock(**{"node_modules/react": entry}))


def test_an_entry_whose_path_names_one_package_but_fetches_another_is_reported() -> None:
    lock = _lock(**{"node_modules/react": _entry("preact")})

    assert check.lockfile_violations(lock)


def test_a_declared_top_level_alias_is_accepted_and_judged_by_its_real_name() -> None:
    aliased = _entry("real-package", name="real-package")
    lock = _lock(**{"node_modules/alias": aliased})
    manifest = {"dependencies": {"alias": "npm:real-package@^1.0.0"}}

    assert check.declared_aliases(manifest) == {"alias": "real-package"}
    assert check.lockfile_violations(lock, check.declared_aliases(manifest)) == []
    assert check.lockfile_names(lock) == {"real-package"}


@pytest.mark.parametrize(
    ("path", "declared"),
    [
        ("node_modules/alias", {}),  # nothing in package.json says this alias exists
        ("node_modules/alias", {"alias": "other-package"}),  # declared for a different package
        ("node_modules/x/node_modules/alias", {"alias": "real-package"}),  # not top level
    ],
)
def test_an_undeclared_alias_is_reported_so_a_path_cannot_hide_another_package(
    path: str, declared: dict[str, str]
) -> None:
    lock = _lock(**{path: _entry("real-package", name="real-package")})

    assert any("alias" in problem for problem in check.lockfile_violations(lock, declared))


@pytest.mark.parametrize(
    "version",
    [
        "1.0.0/../../evil",
        "1.0.0%2f..%2fevil",
        "1.0.0?x=1",
        "1.0.0#frag",
        "latest",
        "1.0",
        "",
        "../1.0.0",
    ],
)
def test_a_version_with_path_or_url_syntax_cannot_steer_the_tarball_url(version: str) -> None:
    entry = {
        "version": version,
        "resolved": f"https://registry.npmjs.org/react/-/react-{version}.tgz",
        "integrity": _INTEGRITY,
    }

    assert check.lockfile_violations(_lock(**{"node_modules/react": entry}))


def test_prerelease_and_build_versions_are_plain_semver() -> None:
    for version in ("1.0.0-rc.1", "2.3.4-beta.2+build.5"):
        lock = _lock(**{"node_modules/react": _entry("react", version)})
        assert check.lockfile_violations(lock) == [], version


@pytest.mark.parametrize("flag", ["link", "inBundle"])
def test_link_and_bundled_entries_are_reported_not_skipped(flag: str) -> None:
    lock = _lock(**{"node_modules/react": _entry("react"), "node_modules/sneaky": {flag: True}})

    assert any("sneaky" in problem for problem in check.lockfile_violations(lock))


@pytest.mark.parametrize(
    "lock",
    [
        {},
        {"lockfileVersion": 3},
        {"lockfileVersion": 3, "packages": {}},
        {"lockfileVersion": 3, "packages": {"": {}}},
        {"lockfileVersion": 3, "packages": []},
        {"lockfileVersion": 3, "packages": "oops"},
    ],
)
def test_a_lockfile_with_no_usable_packages_fails_closed(lock: dict[str, Any]) -> None:
    assert check.lockfile_violations(lock)


def test_an_older_lockfile_version_or_a_legacy_tree_is_reported() -> None:
    good = _lock(**{"node_modules/react": _entry("react")})

    assert check.lockfile_violations({**good, "lockfileVersion": 2})
    assert check.lockfile_violations({**good, "dependencies": {"react": {"version": "9.9.9"}}})
    assert check.lockfile_violations(good) == []


def test_a_non_object_entry_is_reported() -> None:
    lock = _lock(**{"node_modules/react": _entry("react")})
    lock["packages"]["node_modules/bad"] = "not-an-object"

    assert any("bad" in problem for problem in check.lockfile_violations(lock))


def test_main_fails_when_the_head_lockfile_is_missing(tmp_path: Path) -> None:
    manifest = tmp_path / "package.json"
    manifest.write_text("{}", encoding="utf-8")

    status = check.main(
        ["check", str(manifest), str(manifest), str(manifest), str(tmp_path / "missing.json")]
    )

    assert status == 1


def test_transitive_names_new_in_the_head_lockfile_are_the_ones_checked() -> None:
    base = _lock(**{"node_modules/react": _entry("react")})
    head = _lock(
        **{
            "node_modules/react": _entry("react", "1.2.4"),
            "node_modules/left-pad": _entry("left-pad"),
            "node_modules/x/node_modules/left-pad": _entry("left-pad", "0.1.0"),
        }
    )

    assert check.lockfile_names(head) - check.lockfile_names(base) == {"left-pad"}


def test_main_fails_on_a_tampered_lockfile_before_any_network_call(tmp_path: Path) -> None:
    manifest = tmp_path / "package.json"
    manifest.write_text("{}", encoding="utf-8")
    bad = tmp_path / "lock.json"
    bad.write_text(json.dumps(_lock(**{"node_modules/react": _entry("preact")})), encoding="utf-8")

    assert check.main(["check", str(manifest), str(manifest), str(manifest), str(bad)]) == 1
