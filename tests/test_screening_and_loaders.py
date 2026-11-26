import importlib.util
from pathlib import Path

from amlagent.data import load_amlworld, load_sdn
from amlagent.screening import name_score, normalize, screen

ROOT = Path(__file__).resolve().parents[1]
SDN = load_sdn()


def test_normalize_handles_suffixes_punctuation_accents_and_plurals():
    assert normalize("Körvat Maritime Holdings, Ltd.") == ["KORVAT", "MARITIME", "HOLDING"]
    assert normalize("Velmora Trading F.Z.E.") == ["VELMORA", "TRADING", "F", "Z", "E"]


def test_word_order_and_missing_middle_name_still_match():
    assert name_score("Edmund Quillon", "QUILLON, Edmund Avery") >= 0.9


def test_generic_company_words_do_not_create_matches():
    assert not screen("Aldane Holdings Ltd", "CY", SDN)["hit"]


def test_hit_records_whether_the_country_agrees():
    r = screen("Korvat Marine Supplies Ltd", "CA", SDN)
    assert r["hit"] and r["country_agrees"] is False
    assert screen("Korvat Maritime Holding", "MT", SDN)["country_agrees"] is True


def test_sdn_loader_reads_official_layout_with_nulls_and_optional_header(tmp_path):
    (tmp_path / "SDN.CSV").write_text('ent_num,SDN_Name,SDN_Type\n36,"AEROCARIBBEAN AIRLINES",-0-,CUBA,-0-,-0-,-0-,-0-,-0-,-0-,-0-,-0-\n')
    (tmp_path / "ALT.CSV").write_text("36,12,a.k.a.,AERO-CARIBBEAN,-0-\n")
    (tmp_path / "ADD.CSV").write_text("36,25,-0-,Havana,Cuba,-0-\n")
    [e] = load_sdn(tmp_path)
    assert (e["name"], e["type"], e["aliases"], e["countries"]) == ("AEROCARIBBEAN AIRLINES", "entity", ["AERO-CARIBBEAN"], {"Cuba"})


def test_amlworld_loader_and_runner(tmp_path):
    rows = ["Timestamp,From Bank,Account,To Bank,Account,Amount Received,Receiving Currency,Amount Paid,Payment Currency,Payment Format,Is Laundering"]
    for k in range(9):  # nine different senders into one account in a day, then out: fan-in
        rows.append(f"2022/09/01 0{k}:10,{10 + k},S{k},070,TARGET,900.00,US Dollar,900.00,US Dollar,ACH,1")
    rows.append("2022/09/01 11:00,070,TARGET,099,OUT,8000.00,US Dollar,8000.00,US Dollar,Wire,1")
    rows.append("2022/09/02 12:00,050,A,051,B,40.00,US Dollar,40.00,US Dollar,Credit Card,0")
    f = tmp_path / "HI-Small_Trans.csv"
    f.write_text("\n".join(rows) + "\n")
    txns = load_amlworld(f)
    assert txns[0]["to_acct"] == "070:TARGET" and txns[-2]["channel"] == "wire" and txns[-1]["label"] == 0
    spec = importlib.util.spec_from_file_location("run_amlworld", ROOT / "scripts" / "run_amlworld.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = mod.evaluate(txns)
    assert r["by_rule"]["FAN_IN"]["with_laundering"] == 1 and r["laundering_txn_recall"] > 0
