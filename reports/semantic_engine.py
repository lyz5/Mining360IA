from datetime import date

from .powerbi import resolve_dataset_roles
from .semantic_dictionary import get_dataset_semantics, get_primary_measure


def _escape_dax_string(value: str) -> str:
    return str(value).replace('"', '""')


def _escape_dax_identifier(value: str) -> str:
    return str(value).replace("]", "]]")


def _escape_dax_table(value: str) -> str:
    return str(value).replace("'", "''")


def dax_column(table: str, column: str) -> str:
    return f"'{_escape_dax_table(table)}'[{_escape_dax_identifier(column)}]"


def dax_measure(measure: str) -> str:
    return f"[{_escape_dax_identifier(measure)}]"


def build_availability_question(dataset_name: str, year: int, month: int, model: str, site: str) -> dict:
    semantics = get_dataset_semantics(dataset_name)
    dataset_id = semantics.get("dataset_id", "")
    measure = get_primary_measure(dataset_name, "availability", "Avail Per Equip")
    date_table = semantics.get("date_table", {}).get("table", "bravo")
    date_column = semantics.get("date_table", {}).get("primary_date_column", "Date")

    equipment = semantics.get("entities", {}).get("equipment", {})
    equipment_table = equipment.get("table", "EquipmentList")
    model_column = (
        equipment.get("columns", {})
        .get("model", {})
        .get("primary", "Model")
    )

    mine_site = semantics.get("entities", {}).get("mine_site", {})
    site_table = mine_site.get("table", "MinesiteList")
    site_column = (
        mine_site.get("columns", {})
        .get("site", {})
        .get("primary", "Minesite")
    )

    question = f"Availability for {model} at {site} in {year}-{month:02d}"
    rls_role = resolve_dataset_roles(dataset_name, [site])[0] if resolve_dataset_roles(dataset_name, [site]) else site
    dax_query = f"""
EVALUATE
ROW(
    "Dataset", "{_escape_dax_string(dataset_name)}",
    "Question", "{_escape_dax_string(question)}",
    "Measure", "{_escape_dax_string(measure)}",
    "Value",
        CALCULATE(
            {dax_measure(measure)},
            TREATAS({{"{_escape_dax_string(model)}"}}, {dax_column(equipment_table, model_column)}),
            TREATAS({{"{_escape_dax_string(site)}"}}, {dax_column(site_table, site_column)}),
            DATESBETWEEN(
                {dax_column(date_table, date_column)},
                DATE({year}, {month}, 1),
                EOMONTH(DATE({year}, {month}, 1), 0)
            )
        )
)
""".strip()
    return {
        "dataset": dataset_name,
        "dataset_id": dataset_id,
        "metric": "availability",
        "measure": measure,
        "question": question,
        "rls_role": rls_role,
        "filters": {
            f"{equipment_table}[{model_column}]": model,
            f"{site_table}[{site_column}]": site,
            f"{date_table}[{date_column}]": f"{year}-{month:02d}",
        },
        "period": {
            "year": year,
            "month": month,
            "start_date": date(year, month, 1).isoformat(),
        },
        "dax": dax_query,
    }


def build_availability_matrix_question(
    dataset_name: str,
    site: str,
    end_date: date,
    months: int = 12,
) -> dict:
    semantics = get_dataset_semantics(dataset_name)
    dataset_id = semantics.get("dataset_id", "")
    measure = get_primary_measure(dataset_name, "availability", "Avail Per Equip")
    rls_role = resolve_dataset_roles(dataset_name, [site])[0] if resolve_dataset_roles(dataset_name, [site]) else site

    dax_query = f"""
EVALUATE
SUMMARIZECOLUMNS(
    'EquipmentList_MiningProd'[Model],
    'Date'[Year Month Number],
    'Date'[Year Month],
    TREATAS({{"{_escape_dax_string(site)}"}}, 'MineSiteList_MiningProd'[MineSite]),
    DATESINPERIOD('Date'[Date], DATE({end_date.year}, {end_date.month}, {end_date.day}), -{months}, MONTH),
    "Availability", {dax_measure(measure)}
)
ORDER BY 'EquipmentList_MiningProd'[Model], 'Date'[Year Month Number]
""".strip()
    return {
        "dataset": dataset_name,
        "dataset_id": dataset_id,
        "metric": "availability",
        "measure": measure,
        "question": f"{measure} by model for {site} over the last {months} months",
        "rls_role": rls_role,
        "filters": {
            "MineSiteList_MiningProd[MineSite]": site,
            "Date": f"last {months} months ending {end_date.isoformat()}",
        },
        "period": {
            "months": months,
            "end_date": end_date.isoformat(),
        },
        "dax": dax_query,
    }
