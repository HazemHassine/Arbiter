from pathlib import Path

from arbiter.make.service import MakeService
from arbiter.models import Risk


def test_make_parsing_targets_and_prerequisites(tmp_path: Path):
    makefile = tmp_path / "Makefile"
    makefile.write_text("""## Targets
.PHONY: all test dev clean destroy

all: test dev

test:  # Run test suite
\tpytest -v

dev: test  # Start development server
\tuvicorn app:app --port 8000

clean:
\trm -rf dist/

destroy:
\tdocker compose down -v
""")
    service = MakeService()
    targets = service.parse(makefile)

    assert "test" in targets
    assert targets["test"] == ["pytest -v"]
    assert "dev" in targets
    assert targets["dev"] == ["uvicorn app:app --port 8000"]
    assert "destroy" in targets

    details = service.parse_details(makefile)
    assert details["test"].description == "Run test suite"
    assert details["dev"].dependencies == ["test"]
    assert details["dev"].ports == [8000]


def test_make_classify_risk(tmp_path: Path):
    service = MakeService()
    assert service.classify("test", ["pytest"]) == Risk.LOW_RISK
    assert service.classify("clean", ["rm build"]) == Risk.HIGH_RISK
    assert service.classify("destroy", ["docker compose down -v"]) == Risk.DESTRUCTIVE


def test_make_inspect(tmp_path: Path):
    makefile = tmp_path / "Makefile"
    makefile.write_text("dev:\n\tnpm run dev -- -p 5173\n")
    service = MakeService()
    inspected = service.inspect(tmp_path, "dev")
    assert inspected["target"] == "dev"
    assert inspected["commands"] == ["npm run dev -- -p 5173"]
    assert inspected["ports"] == [5173]
