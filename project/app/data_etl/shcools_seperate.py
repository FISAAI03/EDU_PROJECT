import pymysql
import pandas as pd
from dotenv import load_dotenv
from urllib.parse import urlparse
import os

# .env 로드
load_dotenv()
mysql_uri = os.getenv("MYSQL_URI")

# MySQL URI 파싱
def parse_mysql_uri(uri):
    parsed = urlparse(uri.replace("mysql+pymysql", "mysql"))
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": parsed.username,
        "password": parsed.password,
        "db": parsed.path.lstrip("/")
    }

# 분할 및 테이블 생성 실행
def split_schools_by_gubun():
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
        df = pd.read_sql("SELECT * FROM schools", conn)
        gubun_values = df['school_gubun'].unique()

        for gubun in gubun_values:
            # 테이블 이름 설정: _list 제거
            table_name = f"schools_{gubun}".replace("_list", "").lower()

            df_filtered = df[df['school_gubun'] == gubun].copy()

            # 테이블 생성 SQL: school_id는 PK이자 FK
            create_sql = f"""
                CREATE TABLE IF NOT EXISTS `{table_name}` (
                    school_id INT PRIMARY KEY,
                    name VARCHAR(255),
                    school_gubun VARCHAR(50),
                    school_type VARCHAR(100),
                    est_type VARCHAR(50),
                    region VARCHAR(50),
                    address VARCHAR(255),
                    link TEXT,
                    FOREIGN KEY (school_id) REFERENCES schools(school_id) ON DELETE CASCADE
                );
            """

            with conn.cursor() as cur:
                cur.execute(create_sql)
                conn.commit()

                # INSERT
                insert_sql = f"""
                    INSERT INTO `{table_name}` (
                        school_id, name, school_gubun, school_type,
                        est_type, region, address, link
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
                values = df_filtered[
                    ['school_id', 'name', 'school_gubun', 'school_type',
                    'est_type', 'region', 'address', 'link']
                ].values.tolist()

                cur.executemany(insert_sql, values)
                conn.commit()

            print(f"✅ {gubun} → {table_name} 테이블로 {len(df_filtered)}건 분할 완료")

    finally:
        conn.close()

# 실행
if __name__ == "__main__":
    split_schools_by_gubun()
