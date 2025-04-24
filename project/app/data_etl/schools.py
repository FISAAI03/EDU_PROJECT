import requests
import pymysql
import os
from urllib.parse import urlparse
from dotenv import load_dotenv

# .env 로드
load_dotenv()
mysql_uri = os.getenv("MYSQL_URI")
api_key = os.getenv("CAREER_API_KEY")

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

# 테이블 생성 (school_type_2 제거)
def create_schools_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schools (
                school_id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255),
                school_gubun VARCHAR(50),
                school_type VARCHAR(100),
                est_type VARCHAR(50),
                region VARCHAR(50),
                address VARCHAR(255),
                link TEXT
            );
        """)
    conn.commit()
    print("✅ 'schools' 테이블 생성 완료 또는 이미 존재")

# API 수집
def fetch_schools():
    url = "https://www.career.go.kr/cnet/openapi/getOpenApi"
    gubuns = ["elem_list", "midd_list", "high_list", "univ_list", "spec_list", "alte_list"]
    all_results = []

    for gubun in gubuns:
        print(f"📥 {gubun} 수집 중...")
        params = {
            "apiKey": api_key,
            "svcType": "api",
            "svcCode": "SCHOOL",
            "contentType": "json",
            "gubun": gubun,
            "thisPage": 1,
            "perPage": 1000
        }
        while True:
            res = requests.get(url, params=params)
            res.raise_for_status()
            data = res.json()
            items = data.get("dataSearch", {}).get("content", [])
            if not items:
                break
            for item in items:
                item["schoolGubun"] = gubun
            all_results.extend(items)
            if len(items) < params["perPage"]:
                break
            params["thisPage"] += 1

    print(f"✅ 총 수집 개수: {len(all_results)}")
    return all_results

# 저장 로직 (school_type_2 제거)
def save_schools_to_mysql(conn, data):
    with conn.cursor() as cur:
        batch = []
        for idx, item in enumerate(data):
            name = item.get("schoolName")
            school_gubun = item.get("schoolGubun")
            school_type = item.get("schoolType")  # ✅ 단일 컬럼만 저장
            est_type = item.get("estType")
            region = item.get("region")
            address = item.get("adres")
            link = item.get("link")

            batch.append((
                name, school_gubun, school_type,
                est_type, region, address, link
            ))

            if len(batch) >= 500:
                cur.executemany("""
                    INSERT INTO schools (
                        name, school_gubun, school_type,
                        est_type, region, address, link
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, batch)
                conn.commit()
                print(f"✅ 저장 완료: {idx + 1}개")
                batch = []

        if batch:
            cur.executemany("""
                INSERT INTO schools (
                    name, school_gubun, school_type,
                    est_type, region, address, link
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, batch)
            conn.commit()
            print(f"✅ 최종 저장 완료: {len(data)}개")

# 실행 함수
def run_school_etl():
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
        create_schools_table(conn)
        school_data = fetch_schools()
        save_schools_to_mysql(conn, school_data)
    finally:
        conn.close()

# Entry point
if __name__ == "__main__":
    run_school_etl()
