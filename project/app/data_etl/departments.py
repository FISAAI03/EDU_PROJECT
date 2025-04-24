import requests
import pymysql
import os
from urllib.parse import urlparse
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()
mysql_uri = os.getenv("MYSQL_URI")
api_key = os.getenv("CAREER_API_KEY")

def parse_mysql_uri(uri):
    parsed = urlparse(uri.replace("mysql+pymysql", "mysql"))
    return {
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "user": parsed.username,
        "password": parsed.password,
        "db": parsed.path.lstrip("/")
    }

def create_majors_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS majors (
                major_seq VARCHAR(50) PRIMARY KEY,
                i_class VARCHAR(100),
                m_class VARCHAR(100),
                facil_name VARCHAR(255),
                major VARCHAR(255),
                salary VARCHAR(50),
                employment VARCHAR(50),
                department TEXT,
                summary TEXT,
                job TEXT,
                qualifications TEXT,
                interest TEXT,
                property TEXT
            );
        """)
    conn.commit()
    print("✅ 'majors' 테이블 생성 완료 또는 이미 존재")

def fetch_majors():
    url = "https://www.career.go.kr/cnet/openapi/getOpenApi"
    all_majors = []
    this_page = 1
    per_page = 1000

    while True:
        params = {
            "apiKey": api_key,
            "svcType": "api",
            "svcCode": "MAJOR",
            "contentType": "json",
            "gubun": "univ_list",
            "thisPage": this_page,
            "perPage": per_page
        }
        res = requests.get(url, params=params)
        res.raise_for_status()
        data = res.json()
        content = data.get("dataSearch", {}).get("content", [])
        if not content:
            break
        all_majors.extend(content)
        if len(content) < per_page:
            break
        this_page += 1

    print(f"✅ 총 학과 수집 개수: {len(all_majors)}")
    return all_majors

def save_majors_to_mysql(conn, majors):
    with conn.cursor() as cur:
        batch = []
        for idx, item in enumerate(majors):
            batch.append((
                item.get("majorSeq"),
                item.get("lClass"),
                item.get("mClass"),
                item.get("facilName"),
                item.get("major"),
                item.get("salary"),
                item.get("employment"),
                item.get("department"),
                item.get("summary"),
                item.get("job"),
                item.get("qualifications"),
                item.get("interest"),
                item.get("property")
            ))

            if len(batch) >= 500:
                cur.executemany("""
                    INSERT INTO majors (
                        major_seq, i_class, m_class, facil_name, major,
                        salary, employment, department, summary, job,
                        qualifications, interest, property
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        i_class = VALUES(i_class),
                        m_class = VALUES(m_class),
                        facil_name = VALUES(facil_name),
                        major = VALUES(major),
                        salary = VALUES(salary),
                        employment = VALUES(employment),
                        department = VALUES(department),
                        summary = VALUES(summary),
                        job = VALUES(job),
                        qualifications = VALUES(qualifications),
                        interest = VALUES(interest),
                        property = VALUES(property);
                """, batch)
                conn.commit()
                print(f"✅ 저장 완료: {idx + 1}개")
                batch = []

        if batch:
            cur.executemany("""
                INSERT INTO majors (
                    major_seq, i_class, m_class, facil_name, major,
                    salary, employment, department, summary, job,
                    qualifications, interest, property
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    i_class = VALUES(i_class),
                    m_class = VALUES(m_class),
                    facil_name = VALUES(facil_name),
                    major = VALUES(major),
                    salary = VALUES(salary),
                    employment = VALUES(employment),
                    department = VALUES(department),
                    summary = VALUES(summary),
                    job = VALUES(job),
                    qualifications = VALUES(qualifications),
                    interest = VALUES(interest),
                    property = VALUES(property);
            """, batch)
            conn.commit()
            print(f"✅ 최종 저장 완료: {len(majors)}개")

def run_major_etl():
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
        create_majors_table(conn)
        major_data = fetch_majors()
        save_majors_to_mysql(conn, major_data)
    finally:
        conn.close()

if __name__ == "__main__":
    run_major_etl()
