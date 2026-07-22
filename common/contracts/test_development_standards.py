import unittest

from common import verify_development_standards as standards


class MatlabBuildOnlyContractTests(unittest.TestCase):
    example_path = standards.REPO_ROOT / "common" / "example.m"

    def test_unmarked_matlab_may_create_a_study(self):
        source = "model.study.create('std1');"
        self.assertEqual(standards.check_matlab_source(self.example_path, source), [])

    def test_marked_matlab_rejects_solver_operations(self):
        source = "\n".join(
            (
                "% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY",
                "model.study.create('std1');",
                "mphsave(model, outputPath);",
            )
        )
        errors = standards.check_matlab_source(self.example_path, source)
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("MATLAB_BUILD_ONLY" in error for error in errors))

    def test_marked_matlab_allows_geometry_run(self):
        source = "\n".join(
            (
                "% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY",
                "geom.feature.create('vac', 'Cylinder');",
                "geom.run;",
                "mphgeominfo(model, 'geom1');",
            )
        )
        self.assertEqual(standards.check_matlab_source(self.example_path, source), [])

    def test_marked_matlab_ignores_forbidden_words_in_comments(self):
        source = "\n".join(
            (
                "% REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY",
                "% Never call model.study.create or mphsave from this task.",
                "geom.run;",
            )
        )
        self.assertEqual(standards.check_matlab_source(self.example_path, source), [])


if __name__ == "__main__":
    unittest.main()
