import requests
import pymysql
import os
import time
import xml.etree.ElementTree as ET
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

# 테이블 삭제 및 재생성
def recreate_majors_table(conn):
    with conn.cursor() as cur:
        # 관련 테이블 모두 삭제
        print("🔄 기존 테이블 삭제 중...")
        cur.execute("DROP TABLE IF EXISTS qualifications;")
        cur.execute("DROP TABLE IF EXISTS subjects;")
        cur.execute("DROP TABLE IF EXISTS departments;")
        cur.execute("DROP TABLE IF EXISTS majors;")
        conn.commit()
        
        # 새 구조로 테이블 생성
        print("🔄 새 구조로 테이블 생성 중...")
        cur.execute("""
            CREATE TABLE majors (
                seq INT PRIMARY KEY,
                l_class VARCHAR(255),
                m_class VARCHAR(255),
                facil_name TEXT,
                total_count INT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
        """)
        conn.commit()
        print("✅ 테이블 재생성 완료")

# API 응답 디버깅 함수
def debug_api_response(response, seq=None):
    debug_dir = "debug_logs"
    if not os.path.exists(debug_dir):
        os.makedirs(debug_dir)
    
    filename = f"{debug_dir}/api_response_{seq if seq else 'list'}.xml"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(response.text)
    
    print(f"🔍 API 응답 저장됨: {filename}")

# 전공 목록 가져오기
def fetch_major_list():
    print("📥 전공 목록 수집 중...")
    url = "https://www.career.go.kr/cnet/openapi/getOpenApi"
    major_list = []
    
    current_page = 1
    per_page = 100
    
    while True:
        params = {
            "apiKey": api_key,
            "svcType": "api",
            "svcCode": "MAJOR",
            "contentType": "xml",
            "gubun": "univ_list",
            "thisPage": current_page,
            "perPage": per_page
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            # 첫 페이지 응답 디버깅
            if current_page == 1:
                debug_api_response(response)
            
            # XML 파싱
            try:
                root = ET.fromstring(response.content)
            except ET.ParseError as e:
                print(f"❌ XML 파싱 오류: {str(e)}")
                print(f"응답 내용: {response.text[:500]}...")  # 처음 500자만 출력
                break
            
            # 첫 페이지에서만 총 개수 확인
            total_count_elem = root.find('.//totalCount')
            if current_page == 1 and total_count_elem is not None:
                total_count = int(total_count_elem.text)
                print(f"🔍 API에서 총 {total_count}개의 전공 데이터 확인")
            
            # 현재 페이지 데이터 추출
            items = []
            for item in root.findall('.//content'):
                major_data = {}
                for child in item:
                    # XML 태그와 값을 딕셔너리에 저장
                    major_data[child.tag] = child.text
                
                # 필요한 필드가 있는지 확인
                if 'majorSeq' not in major_data:
                    print(f"⚠️ majorSeq 없는 항목 발견: {major_data}")
                    continue
                    
                items.append(major_data)
            
            if not items:
                print("⚠️ 더 이상 항목이 없습니다.")
                break
                
            major_list.extend(items)
            print(f"📄 페이지 {current_page}: {len(items)}개 수집")
            
            # 디버깅: 첫 항목 출력
            if items and current_page == 1:
                print(f"🔍 첫 번째 항목 샘플: {items[0]}")
            
            # 다음 페이지가 없으면 종료
            if len(items) < per_page:
                break
                
            current_page += 1
            # API 요청 간 간격 두기
            time.sleep(0.5)
            
        except Exception as e:
            print(f"❌ 전공 목록 수집 중 오류 발생: {str(e)}")
            break
    
    print(f"✅ 총 수집된 전공 목록: {len(major_list)}개")
    return major_list

# 저장 헬퍼 함수 - 안전하게 값 가져오기
def safe_get(data_dict, key, default=''):
    if data_dict is None:
        return default
    value = data_dict.get(key, default)
    return value if value is not None else default

# 전공 데이터 MySQL에 저장
def save_majors_to_mysql(conn, major_list):
    total_saved = 0
    total_failed = 0
    
    with conn.cursor() as cur:
        for idx, major in enumerate(major_list):
            seq = safe_get(major, 'majorSeq')
            if not seq:
                print(f"⚠️ {idx+1}번째 항목에 majorSeq가 없습니다. 건너뜁니다.")
                total_failed += 1
                continue
            
            try:
                total_count_val = safe_get(major, 'totalCount', '0')
                # 숫자가 아닌 경우 기본값 0 사용
                try:
                    total_count = int(total_count_val)
                except ValueError:
                    total_count = 0
                
                # 삽입 (중복키 발생 시 업데이트)
                cur.execute("""
                    INSERT INTO majors 
                    (seq, l_class, m_class, facil_name, total_count) 
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                    l_class = VALUES(l_class),
                    m_class = VALUES(m_class),
                    facil_name = VALUES(facil_name),
                    total_count = VALUES(total_count),
                    updated_at = CURRENT_TIMESTAMP
                """, (
                    seq,
                    safe_get(major, 'lClass'),
                    safe_get(major, 'mClass'),
                    safe_get(major, 'facilName'),
                    total_count
                ))
                total_saved += 1
                
                # 100개마다 커밋
                if (idx + 1) % 100 == 0:
                    conn.commit()
                    print(f"✅ {idx + 1}개 처리 중 커밋 완료")
                
                # 진행 상황 표시 (20개마다)
                if (idx + 1) % 20 == 0:
                    print(f"🔄 진행 상황: {idx + 1}/{len(major_list)} 처리 중...")
                
            except Exception as e:
                total_failed += 1
                print(f"❌ {idx+1}번째 항목 처리 중 오류 발생: {str(e)}")
        
        # 최종 커밋
        conn.commit()
    
    return total_saved, total_failed

# 실행 함수
def run_major_etl():
    print("🚀 전공 데이터 ETL 작업 시작")
    
    try:
        parsed = parse_mysql_uri(mysql_uri)
        conn = pymysql.connect(
            host=parsed["host"],
            port=parsed["port"],
            user=parsed["user"],
            password=parsed["password"],
            db=parsed["db"],
            charset="utf8mb4"
        )

        # 테이블 삭제 및 재생성
        recreate_majors_table(conn)
        
        # 테이블 구조 확인
        with conn.cursor() as cur:
            cur.execute("DESCRIBE majors")
            majors_columns = cur.fetchall()
            print(f"🔍 majors 테이블 컬럼: {[col[0] for col in majors_columns]}")
        
        # 전공 목록 수집
        major_list = fetch_major_list()
        
        if major_list:
            # 전공 데이터 저장
            total_saved, total_failed = save_majors_to_mysql(conn, major_list)
            print(f"📊 처리 결과: 총 {len(major_list)}개 중 {total_saved}개 성공, {total_failed}개 실패")
            
            # 저장된 데이터 확인
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM majors")
                count = cur.fetchone()[0]
                print(f"📊 majors 테이블에 저장된 레코드 수: {count}")
                
                if count > 0:
                    cur.execute("SELECT seq, l_class, m_class, facil_name FROM majors LIMIT 5")
                    samples = cur.fetchall()
                    print("📋 저장된 데이터 샘플:")
                    for sample in samples:
                        print(f"  - ID: {sample[0]}, L클래스: {sample[1]}, M클래스: {sample[2]}, 시설명: {sample[3][:30]}...")
        else:
            print("⚠️ 수집된 전공 목록이 없습니다.")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ ETL 작업 중 오류 발생: {str(e)}")
    
    print("🏁 전공 데이터 ETL 작업 완료")

# Entry point
if __name__ == "__main__":
    run_major_etl()