import json
import subprocess
import sys
from pathlib import Path

from kbsearch.cli import main


def test_cli_build_query_update_and_remove_workflow(tmp_path, capsys):
    docs = tmp_path / "manuals"
    docs.mkdir()
    path = docs / "fridge.txt"
    path.write_text("冰箱压缩机异响\n压缩机噪音且不制冷", encoding="utf-8")
    other = docs / "washer.txt"
    other.write_text("洗衣机不排水，水泵异响", encoding="utf-8")
    syn = tmp_path / "syn.txt"
    syn.write_text("冰箱=冰柜\n维修=修理\n", encoding="utf-8")
    index = tmp_path / "idx.json"

    rc = main(["--index", str(index), "--directory", str(docs),
               "--synonyms", str(syn)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "文档总数=2" in out

    rc = main(["--index", str(index),
               "--query", "压缩机 AND (异响 OR 不制冷)", "--top-k", "10"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "doc_id=fridge.txt" in out
    assert "score=" in out
    # Boolean results must be score sorted; the exact multi-term hit is first.
    assert out.splitlines()[0].startswith("doc_id=fridge.txt")

    path.write_text("冰箱全新故障 evaporator 更换", encoding="utf-8")
    rc = main(["--index", str(index), "--update", str(path)])
    assert rc == 0
    rc = main(["--index", str(index), "--query", "异响"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "doc_id=fridge.txt" not in out
    assert "doc_id=washer.txt" in out

    rc = main(["--index", str(index), "--query", "evaporator"])
    out = capsys.readouterr().out
    assert "doc_id=fridge.txt" in out

    payload = json.loads(index.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert "postings" in payload and "synonyms" in payload


def test_module_launcher_interactive_and_reindex():
    # Smoke-test the runnable entry point documented in README.
    proc = subprocess.run(
        [sys.executable, "-m", "kbsearch", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    assert "kbsearch-cli" in proc.stdout


def test_reindex_preserves_existing_synonyms(tmp_path, capsys):
    docs = tmp_path / "manuals"
    docs.mkdir()
    (docs / "a.txt").write_text("冰柜故障", encoding="utf-8")
    syn = tmp_path / "syn.txt"
    syn.write_text("冰箱=冰柜\n", encoding="utf-8")
    index = tmp_path / "idx.json"
    assert main(["--index", str(index), "--directory", str(docs),
                 "--synonyms", str(syn)]) == 0
    assert main(["--index", str(index), "--directory", str(docs),
                 "--reindex"]) == 0
    assert main(["--index", str(index), "--query", "冰箱"]) == 0
    out = capsys.readouterr().out
    assert "doc_id=a.txt" in out
