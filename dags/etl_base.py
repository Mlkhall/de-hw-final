import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import TypeAlias

import pandas as pd
import pendulum
from airflow.decorators import dag, task

now = pendulum.now()

ProfitTable: TypeAlias = pd.DataFrame


@task(task_id="extract", execution_timeout=timedelta(minutes=5))
def extract_profit_table(csv_source: Path = Path("data/profit_table.csv")) -> ProfitTable:
    """Задача на извлечение данных из CSV-файла.

    Необходимые данные хранятся в таблице profit_table.csv.
    Это таблица, в которой для каждого клиента по 10-ти продуктам собраны суммы и количества транзакций за каждый месяц.

    Args:
        csv_source (Path): Путь к CSV-файлу.

    Returns:
        ProfitTable: Датафрейм с данными из CSV-файла.
    """
    return pd.read_csv(csv_source)


@task(task_id="transform", execution_timeout=timedelta(minutes=5), retries=5)
def transform_profit_table(profit_table: ProfitTable, current_date: date) -> ProfitTable:
    """Задача на сбор таблицы флагов активности по продуктам.
    Собирает таблицу флагов активности по продуктам на основании прибыли и количеству совершёных транзакций.

    Args:
        profit_table (ProfitTable): Таблица с суммой и кол-вом транзакций.
        current_date (date): Дата расчёта флагов активности.

    Returns:
        Датафрейм для вычисления флагов за указанную дату.
    """
    logger = logging.getLogger("airflow.task")

    current_date = pd.to_datetime(current_date)
    start_date = current_date - pd.DateOffset(months=2)
    end_date = current_date + pd.DateOffset(months=1)

    date_list = pd.date_range(
        start=start_date, end=end_date, freq='M'
    ).strftime('%Y-%m-01')

    df_tmp = (
        profit_table[profit_table['date'].isin(date_list)]
        .drop('date', axis=1)
        .groupby('id')
        .sum()
    )

    product_list = ('a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j')
    for product in product_list:
        df_tmp[f'flag_{product}'] = (
            df_tmp.apply(
                lambda x: x[f'sum_{product}'] != 0 and x[f'count_{product}'] != 0,
                axis=1
            ).astype(int)
        )

    df_tmp = df_tmp.filter(regex='flag').reset_index()
    logger.info(f"Transformed profit table for {current_date}")
    return df_tmp


@task(task_id="load", execution_timeout=timedelta(minutes=5))
def load_activity_table(
    profit_table: ProfitTable,
    csv_target: Path = Path("data/activity_table.csv")
) -> None:
    """Задача на сохранение таблицы флагов активности в CSV-файл.

    Args:
        profit_table (ProfitTable): Таблица с флагами активности.
        csv_target (Path): Путь к CSV-файлу.
    """

    if os.stat(csv_target).st_size == 0:
        profit_table.to_csv(csv_target, index=False)
    else:
        profit_table.to_csv(csv_target, mode='a', header=False, index=False)


@dag(dag_display_name="ETL Pipeline", start_date=now, schedule="0 0 5 * *", tags=["mfti"], dag_id="etl_base")
def etl_base():
    extract = extract_profit_table()
    transform = transform_profit_table(extract, date.today())
    load = load_activity_table(transform)

    extract >> transform >> load


dag_etl = etl_base()


if __name__ == "__main__":
    dag_etl.test()
