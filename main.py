import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from loguru import logger

logger.remove()
logger.add("./log/create_all_tables.log", rotation="10 MB", retention="10 days")
logger.add(
    sys.stdout,
    colorize=True,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",  # noqa: E501
)


def check_env_var(env_var_name: str) -> bool:
    """環境変数が設定されているか確認する

    Args:
        env_var_name (str): 環境変数名

    Returns:
        bool: 環境変数が設定されているかどうか
    """
    if not os.environ(env_var_name):
        logger.warning(f"Environment variable {env_var_name} is not set.")
        return False
    logger.info(f"{env_var_name}: {os.environ(env_var_name)}")
    return True


def get_ddl_file_names(folder_path: str) -> list:
    """DDLファイル名を取得する

    Args:
        folder_path (str): DDLファイルが格納されているフォルダのパス

    Returns:
        list: DDLファイル名のリスト
    """
    try:
        path = Path(folder_path)
        ddl_file_names = [file for file in path.iterdir() if file.suffix == ".sql"]
    except FileNotFoundError:
        logger.error(f"Folder {folder_path} not found.")
    except PermissionError:
        logger.error(f"No permission to read folder {folder_path}.")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
    return ddl_file_names


def load_query_from_file(file_path: str) -> str:
    """ファイルからクエリを読み込む

    Args:
        file_path (str): クエリファイルのパス

    Returns:
        str: クエリ
    """
    try:
        path = Path(file_path)
        with path.open("rt", encoding="utf-8") as f:
            query = f.read()
    except FileNotFoundError:
        logger.error(f"File {file_path} not found.")
    except OSError:
        logger.error(f"Error occurred while reading file {file_path}.")
    return query


def add_bq_dataset_name_to_query(query: str, table_name: str, dataset_name: str) -> str:
    """クエリにデータセット名を追加する

    Args:
        query (str): クエリ
        table_name (str): テーブル名
        dataset_name (str): データセット名

    Returns:
        str: データセット名が追加されたクエリ
    """
    # クエリ内にテーブル名が含まれている場合、データセット名を追加する
    if table_name in query:
        query = query.replace(f"{table_name}", f"{dataset_name}.{table_name}")
    return query


def check_table_exists(
    client: bigquery.Client, table_name: str, dataset_name: str
) -> bool:
    """テーブルが存在するか確認する

    Args:
        client (bigquery.Client): BigQueryクライアント
        table_name (str): テーブル名
        dataset_name (str): データセット名

    Returns:
        bool: テーブルが存在するかどうか
    """
    try:
        dataset_ref = client.dataset(dataset_name)
        table_ref = dataset_ref.table(table_name)
        table = client.get_table(table_ref)
    except NotFound:
        return False
    except Exception as e:
        logger.error(f"Unexpected error occurred while checking table existence: {e}")
        raise Exception(f"Error checking if table exists: {e}") from e  # noqa: EM102
    else:
        return True


def create_table_from_ddl(client: bigquery.Client, ddl_file_path: str) -> None:
    """DDLファイルからテーブルを作成する

    Args:
        ddl_file_path (str): DDLファイルのパス
    """
    query = load_query_from_file(ddl_file_path)
    if not query:
        return
    query = add_bq_dataset_name_to_query(query, table_name, bq_dataset_name)

    job_config = bigquery.QueryJobConfig()
    job_config.use_legacy_sql = False

    try:
        logger.info("Executing query")
        query_job = client.query(query, job_config=job_config)
        query_job.result()
        logger.info("Query is executed successfully.")
    except bigquery.exceptions.QueryTimeout as e:
        logger.error(f"Query timed out: {e}")
    except Exception as e:
        logger.error(f"Error occurred while executing query: {e}")


if __name__ == "__main__":
    load_dotenv()

    gcp_project_id = os.environ("GCP_PROJECT_ID")
    gcp_region = os.environ("GCP_REGION")
    bq_dataset_name = os.environ("BQ_DATASET_NAME")
    ddl_folder_path = os.environ("DDL_FOLDER_PATH")

    if not all(
        [
            check_env_var("GCP_PROJECT_ID"),
            check_env_var("GCP_REGION"),
            check_env_var("BQ_DATASET_NAME"),
            check_env_var("DDL_FOLDER_PATH"),
        ]
    ):
        sys.exit(1)

    bq_client = bigquery.Client(project=gcp_project_id)

    ddl_file_names = get_ddl_file_names(ddl_folder_path)

    for ddl_file_name in ddl_file_names:
        ddl_file_path = f"{ddl_folder_path}/{ddl_file_name}"
        table_name = ddl_file_name.split(".")[0]
        if check_table_exists(bq_client, table_name, bq_dataset_name):
            logger.info(f"Table {bq_dataset_name}.{table_name} already exists.")
            continue
        create_table_from_ddl(bq_client, ddl_file_path)

    logger.info("All tables are created.")
