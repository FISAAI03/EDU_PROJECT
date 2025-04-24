import os
import pymysql
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from urllib.parse import urlparse
import re

# .env 로드
load_dotenv()
mysql_uri = os.getenv("MYSQL_URI")

# URI 파싱
def parse_mysql_uri(uri):
    parsed = urlparse(uri.replace("mysql+pymysql", "mysql"))
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": parsed.username,
        "password": parsed.password,
        "db": parsed.path.lstrip("/")
    }

# 한글 → 영문 컬럼 매핑
COLUMN_MAP = {
    "조사기준일": "survey_date",
    "학제": "edu_level",
    "학교명": "school_name",
    "KEDI\n학교코드": "school_code",
    "학교상태": "school_status",
    "본분교": "campus_type",
    "시도": "region",
    "설립": "establishment_type",
    "과정구분": "course_type",
    "대계열": "major_group",
    "중계열": "mid_major",
    "소계열": "sub_major",
    "학과코드": "dept_code",
    "학과명": "dept_name",
    "학위구분": "degree_type",
    "졸업자_계": "graduates_total",
    "졸업자_남": "graduates_male",
    "졸업자_여": "graduates_female",
    "취업률_계": "emp_rate_total",
    "취업률_남": "emp_rate_male",
    "취업률_여": "emp_rate_female",
    "취업자_합계_계": "employed_total",
    "취업자_합계_남": "employed_male",
    "취업자_합계_여": "employed_female",
    "진학률_계": "advance_rate_total",
    "진학률_남": "advance_rate_male",
    "진학률_여": "advance_rate_female",
    "진학자_계": "advanced_total",
    "진학자_남": "advanced_male",
    "진학자_여": "advanced_female"
    # 필요한 경우 더 추가 가능
}

def map_dtype_to_mysql(dtype):
    if pd.api.types.is_integer_dtype(dtype):
        return "INT"
    elif pd.api.types.is_float_dtype(dtype):
        return "FLOAT"
    elif pd.api.types.is_datetime64_any_dtype(dtype):
        return "DATE"
    else:
        return "VARCHAR(255)"

def create_table_from_excel(conn, df, table_name):
    columns_sql = []
    for col, dtype in df.dtypes.items():
        mysql_type = map_dtype_to_mysql(dtype)
        columns_sql.append(f"`{col}` {mysql_type}")

    create_sql = f"""
        CREATE TABLE IF NOT EXISTS `{table_name}` (
            id INT AUTO_INCREMENT PRIMARY KEY,
            {', '.join(columns_sql)}
        );
    """
    with conn.cursor() as cur:
        cur.execute(create_sql)
    conn.commit()
    print(f"✅ '{table_name}' 테이블 생성 완료")

import numpy as np

def insert_dataframe_to_mysql(conn, df, table_name):
    placeholders = ', '.join(['%s'] * len(df.columns))
    insert_sql = f"""
        INSERT INTO `{table_name}` ({', '.join([f"`{col}`" for col in df.columns])})
        VALUES ({placeholders})
    """
    # NaN → None 변환
    data = df.replace({np.nan: None}).values.tolist()

    with conn.cursor() as cur:
        cur.executemany(insert_sql, data)
    conn.commit()
    print(f"✅ 총 {len(df)}건 업로드 완료")


def run_excel_full_upload(excel_path, table_name):
    df = pd.read_excel(excel_path, engine='openpyxl')

    # 불필요한 Unnamed 열 제거
    df = df.loc[:, ~df.columns.str.contains('^Unnamed')]

    # 컬럼명 영어로 매핑
    df.rename(columns=COLUMN_MAP, inplace=True)

    # 빈 컬럼명 대체 (컬럼명이 누락된 경우 대비)
    df.columns = [col if col else f"col_{i}" for i, col in enumerate(df.columns)]

    parsed = parse_mysql_uri(mysql_uri)
    conn = pymysql.connect(
        host=parsed["host"],
        port=parsed["port"],
        user=parsed["user"],
        password=parsed["password"],
        db=parsed["db"],
        charset="utf8mb4"
    )
    try:
        create_table_from_excel(conn, df, table_name)
        insert_dataframe_to_mysql(conn, df, table_name)
    finally:
        conn.close()

# 실행
if __name__ == "__main__":
    run_excel_full_upload("취업률_데이터.xlsx", "employment_full")
