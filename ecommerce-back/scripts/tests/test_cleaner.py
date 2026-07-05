# -*- coding: utf-8 -*-
"""
Tests unitaires — DataCleaner
==============================
Vérifie le nettoyage des données brutes :
- Parsing des dates (ISO, slash, invalides)
- Parsing des prix (normaux, CFA, négatifs, texte)
- Parsing des quantités (positives, nulles, négatives)
- Traitement des anonymes
- Suppression des doublons
"""

import sys
import os
import pytest
import pandas as pd
from io import StringIO

# Ajout du chemin du module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clean_and_inject import DataCleaner

# ─────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────

@pytest.fixture
def cleaner():
    return DataCleaner("dummy.csv")


# ─────────────────────────────────────────
# TESTS — PARSING DES DATES
# ─────────────────────────────────────────

class TestParseDate:

    def test_date_iso_valide(self, cleaner):
        """Une date ISO-8601 valide doit être retournée telle quelle."""
        assert cleaner._parse_date("2025-03-21T14:22:01") == "2025-03-21T14:22:01"

    def test_date_slash_convertie(self, cleaner):
        """Une date au format YYYY/MM/DD doit être convertie en ISO-8601."""
        assert cleaner._parse_date("2026/03/21 04:13:22") == "2026-03-21T04:13:22"

    def test_date_impossible_rejetee(self, cleaner):
        """Une date avec mois 00 ou jour 99 doit être rejetée."""
        assert cleaner._parse_date("2025-00-99T99:99:99") is None

    def test_date_format_invalide(self, cleaner):
        """Un format inconnu doit retourner None."""
        assert cleaner._parse_date("21-03-2025") is None

    def test_date_vide(self, cleaner):
        """Une chaîne vide doit retourner None."""
        assert cleaner._parse_date("") is None

    def test_date_slash_invalide(self, cleaner):
        """Un format slash avec date impossible doit être rejeté."""
        assert cleaner._parse_date("2025/13/45 25:99:00") is None


# ─────────────────────────────────────────
# TESTS — PARSING DES PRIX
# ─────────────────────────────────────────

class TestParsePrice:

    def test_prix_normal(self, cleaner):
        """Un prix numérique valide doit être retourné comme float."""
        assert cleaner._parse_price("29.99") == 29.99

    def test_prix_cfa(self, cleaner):
        """Un prix avec suffixe CFA doit être extrait correctement."""
        assert cleaner._parse_price("112.09 CFA") == 112.09

    def test_prix_cfa_minuscule(self, cleaner):
        """Le suffixe cfa en minuscule doit aussi fonctionner."""
        assert cleaner._parse_price("500.00 cfa") == 500.00

    def test_prix_negatif_rejete(self, cleaner):
        """Un prix négatif doit être rejeté (None)."""
        assert cleaner._parse_price("-99.99") is None

    def test_prix_zero_rejete(self, cleaner):
        """Un prix nul doit être rejeté."""
        assert cleaner._parse_price("0") is None

    def test_prix_texte_rejete(self, cleaner):
        """Du texte pur doit être rejeté."""
        assert cleaner._parse_price("GRATUIT") is None

    def test_prix_entier(self, cleaner):
        """Un prix entier doit être accepté."""
        assert cleaner._parse_price("450") == 450.0


# ─────────────────────────────────────────
# TESTS — PARSING DES QUANTITÉS
# ─────────────────────────────────────────

class TestParseQty:

    def test_quantite_valide(self, cleaner):
        """Une quantité positive doit être retournée comme entier."""
        assert cleaner._parse_qty("3") == 3

    def test_quantite_negative_rejetee(self, cleaner):
        """Une quantité négative doit être rejetée."""
        assert cleaner._parse_qty("-1") is None

    def test_quantite_zero_rejetee(self, cleaner):
        """Une quantité nulle doit être rejetée."""
        assert cleaner._parse_qty("0") is None

    def test_quantite_texte_rejetee(self, cleaner):
        """Du texte doit être rejeté."""
        assert cleaner._parse_qty("abc") is None

    def test_quantite_float_tronquee(self, cleaner):
        """Un float positif doit être accepté (tronqué en int)."""
        assert cleaner._parse_qty("2") == 2


# ─────────────────────────────────────────
# TESTS — PIPELINE COMPLET
# ─────────────────────────────────────────

class TestPipelineComplet:

    def _make_csv(self, rows: list[dict]) -> str:
        """Génère un CSV en mémoire depuis une liste de dicts."""
        cols = ["transaction_id","customer_id","product_id","product_category",
                "quantity","unit_price","total_amount","transaction_date"]
        lines = [",".join(cols)]
        for r in rows:
            lines.append(",".join(str(r.get(c, "")) for c in cols))
        return "\n".join(lines)

    def _run_cleaner(self, csv_content: str):
        """Lance le cleaner sur un CSV en mémoire."""
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv',
                                         delete=False, encoding='utf-8') as f:
            f.write(csv_content)
            tmp = f.name
        try:
            c = DataCleaner(tmp)
            return c.clean()
        finally:
            os.unlink(tmp)

    def test_ligne_propre_injectee(self):
        """Une ligne valide doit passer le nettoyage."""
        csv = self._make_csv([{
            "transaction_id": "TX-001", "customer_id": "CUST-001",
            "product_id": "PROD-001", "product_category": "Mode",
            "quantity": "2", "unit_price": "29.99",
            "total_amount": "59.98", "transaction_date": "2025-03-12T14:22:01"
        }])
        df_all, df_id = self._run_cleaner(csv)
        assert len(df_all) == 1
        assert len(df_id) == 1

    def test_doublon_supprime(self):
        """Deux lignes identiques → une seule conservée."""
        row = {
            "transaction_id": "TX-001", "customer_id": "CUST-001",
            "product_id": "PROD-001", "product_category": "Mode",
            "quantity": "2", "unit_price": "29.99",
            "total_amount": "59.98", "transaction_date": "2025-03-12T14:22:01"
        }
        csv = self._make_csv([row, row])
        df_all, _ = self._run_cleaner(csv)
        assert len(df_all) == 1

    def test_anonyme_dans_mongodb_pas_neo4j(self):
        """Transaction sans customer_id → dans df_all mais pas df_identified."""
        import tempfile, os
        csv = self._make_csv([{
            "transaction_id": "TX-002", "customer_id": "",
            "product_id": "PROD-001", "product_category": "Mode",
            "quantity": "1", "unit_price": "50.00",
            "total_amount": "50.00", "transaction_date": "2025-03-12T14:22:01"
        }])
        from clean_and_inject import DataCleaner
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write(csv)
            tmp = f.name
        try:
            c = DataCleaner(tmp)
            df_all, df_id = c.clean()
            assert c.stats["anonymous"] == 1
            assert len(df_id) == 0
        finally:
            os.unlink(tmp)

    def test_prix_cfa_corrige(self):
        """Prix '112.09 CFA' doit être corrigé à 112.09."""
        csv = self._make_csv([{
            "transaction_id": "TX-003", "customer_id": "CUST-001",
            "product_id": "PROD-001", "product_category": "Mode",
            "quantity": "1", "unit_price": "112.09 CFA",
            "total_amount": "112.09", "transaction_date": "2025-03-12T14:22:01"
        }])
        df_all, _ = self._run_cleaner(csv)
        assert len(df_all) == 1
        assert df_all.iloc[0]["unit_price"] == 112.09

    def test_date_slash_corrigee(self):
        """Date '2026/03/21 04:13:22' doit être convertie en ISO."""
        csv = self._make_csv([{
            "transaction_id": "TX-004", "customer_id": "CUST-001",
            "product_id": "PROD-001", "product_category": "Mode",
            "quantity": "1", "unit_price": "29.99",
            "total_amount": "29.99", "transaction_date": "2026/03/21 04:13:22"
        }])
        df_all, _ = self._run_cleaner(csv)
        assert len(df_all) == 1
        assert df_all.iloc[0]["transaction_date"] == "2026-03-21T04:13:22"

    def test_quantite_negative_rejetee(self):
        """Quantité négative → stats bad_quantity incrémenté."""
        import tempfile, os
        csv = self._make_csv([{
            "transaction_id": "TX-005", "customer_id": "CUST-001",
            "product_id": "PROD-001", "product_category": "Mode",
            "quantity": "-1", "unit_price": "29.99",
            "total_amount": "-29.99", "transaction_date": "2025-03-12T14:22:01"
        }])
        from clean_and_inject import DataCleaner
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write(csv)
            tmp = f.name
        try:
            c = DataCleaner(tmp)
            c.clean()
            assert c.stats["bad_quantity"] == 1
            assert c.stats["clean"] == 0
        finally:
            os.unlink(tmp)

    def test_total_recalcule(self):
        """Le total_amount doit être recalculé (quantité × prix)."""
        csv = self._make_csv([{
            "transaction_id": "TX-006", "customer_id": "CUST-001",
            "product_id": "PROD-001", "product_category": "Mode",
            "quantity": "3", "unit_price": "10.00",
            "total_amount": "999.99",  # valeur brute incorrecte
            "transaction_date": "2025-03-12T14:22:01"
        }])
        df_all, _ = self._run_cleaner(csv)
        assert len(df_all) == 1
        assert df_all.iloc[0]["total_amount"] == 30.00

    def test_date_invalide_rejetee(self):
        """Date impossible → ligne rejetée, stats bad_date incrémenté."""
        import tempfile, os
        csv = self._make_csv([{
            "transaction_id": "TX-007", "customer_id": "CUST-001",
            "product_id": "PROD-001", "product_category": "Mode",
            "quantity": "1", "unit_price": "29.99",
            "total_amount": "29.99", "transaction_date": "2025-00-99T99:99:99"
        }])
        from clean_and_inject import DataCleaner
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write(csv)
            tmp = f.name
        try:
            c = DataCleaner(tmp)
            c.clean()
            assert c.stats["bad_date"] == 1
            assert c.stats["clean"] == 0
        finally:
            os.unlink(tmp)