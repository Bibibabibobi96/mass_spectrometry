"""Author RF research publications through the installed workflow owner."""

from pathlib import Path

from msplatform.workflows import rf_publication


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
PROFILES = rf_publication.profile_paths(PROJECT_ROOT)
EXPECTED_IDENTITY = rf_publication.EXPECTED_IDENTITY


def resolve(profile: str) -> dict:
    return rf_publication.resolve(
        profile, project_root=PROJECT_ROOT, repository_root=REPOSITORY_ROOT,
        profiles=PROFILES,
    )


def check_variant(variant: str) -> None:
    rf_publication.check_variant(
        variant, project_root=PROJECT_ROOT, repository_root=REPOSITORY_ROOT,
    )


def publish_governance() -> None:
    rf_publication.publish_governance(
        project_root=PROJECT_ROOT, repository_root=REPOSITORY_ROOT,
    )


def publish_budget_design_bindings() -> None:
    rf_publication.publish_budget_design_bindings(
        project_root=PROJECT_ROOT, repository_root=REPOSITORY_ROOT,
    )


def main() -> None:
    rf_publication.main(
        project_root=PROJECT_ROOT, repository_root=REPOSITORY_ROOT, profiles=PROFILES,
    )


if __name__ == "__main__":
    main()
