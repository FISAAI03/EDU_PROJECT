from flask import Blueprint,current_app, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from .models import db, User, UserProfile, JobsInfo, AiResult, EmploymentFull  # ✅ JobsInfo 추가
import logging
import random
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import openai
from elasticsearch import Elasticsearch
from views.character_prompt import build_prompt, generate_greeting # 캐릭터챗 프롬프트 불러오기
from views.models import db, CharacterChatHistory # 캐릭터 챗 대화 저장용



main_bp = Blueprint('main', __name__)


# 공통 함수: 모든 템플릿에 로그인 상태 전달
def get_template_context():
    """모든 템플릿에 공통으로 전달할 컨텍스트를 반환합니다."""
    is_logged_in = 'user_id' in session
    return {'is_logged_in': is_logged_in}

@main_bp.route('/')
def home():
    if request.args.get('force_reload'):
        return redirect(url_for('main.home'))  # 서버 쪽에서 강제 리다이렉트 처리

    profile = None
    job_detail = None

    # 세션 상태 확인
    is_logged_in = 'user_id' in session

    all_schools = EmploymentFull.query.all()
    all_jobs = JobsInfo.query.filter(JobsInfo.salery.isnot(None)).all()

    if len(all_schools) >= 3:
        random_schools = random.sample(all_schools, 3)
    else:
        random_schools = all_schools

    if len(all_jobs) >= 3:
        random_jobs = random.sample(all_jobs, 3)
    else:
        random_jobs = all_jobs

    if is_logged_in:
        profile = UserProfile.query.filter_by(user_id=session['user_id']).first()
        if profile and profile.target_career:
            job_detail = JobsInfo.query.filter_by(job=profile.target_career).first()

    return render_template(
        'index.html',
        profile=profile,
        job_detail=job_detail,
        random_schools=random_schools,
        random_jobs=random_jobs,
        is_logged_in=is_logged_in
    )

@main_bp.route('/register', methods=['GET', 'POST'])
def register():
    # 이미 로그인 되어있으면 홈으로
    if 'user_id' in session:
        return redirect(url_for('main.home'))
        
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')

        if not username or not email or not password:
            flash('모든 필드를 입력해주세요.')
            return redirect(url_for('main.register'))

        if User.query.filter_by(email=email).first():
            flash('이미 등록된 이메일입니다.')
            return redirect(url_for('main.register'))

        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()

        flash('회원가입이 완료되었습니다! 로그인 해주세요.')
        return redirect(url_for('main.home'))

    return render_template('register.html', **get_template_context())


@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    # 이미 로그인 되어있으면 홈으로
    if 'user_id' in session:
        return redirect(url_for('main.home'))
        
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()

        if not user:
            flash("존재하지 않는 이메일입니다.")
            return redirect(url_for('main.login'))

        if not check_password_hash(user.password_hash, password):
            flash("비밀번호가 일치하지 않습니다.")
            return redirect(url_for('main.login'))

        session['user_id'] = user.id
        session['username'] = user.username
        flash(f"{user.username}님 환영합니다!")
        return redirect(url_for('main.home'))

    return render_template('login.html', **get_template_context())


@main_bp.route('/logout')
def logout():
    session.clear()
    flash("로그아웃 되었습니다.")
    # 강제 새로고침 추가_로그인/아웃 리다이렉트 위함
    return redirect(url_for('main.home', force_reload=1))


@main_bp.route('/profile')
def profile():
    if 'user_id' not in session:
        flash("로그인 후 이용해주세요.")
        return redirect(url_for('main.login'))

    profile = UserProfile.query.filter_by(user_id=session['user_id']).first()
    if profile:
        return render_template('profile.html', profile=profile, **get_template_context())
    else:
        flash("아직 프로필 정보가 없습니다. 테스트를 진행해주세요.")
        return redirect(url_for('main.profile_setup'))


@main_bp.route('/profile/setup', methods=['GET', 'POST'])
def profile_setup():
    if 'user_id' not in session:
        flash("로그인 후 이용해주세요.")
        return redirect(url_for('main.login'))

    # 기존 프로필 확인
    existing_profile = UserProfile.query.filter_by(user_id=session['user_id']).first()
    if existing_profile:
        # 이미 프로필이 있으면 edit 페이지로 리다이렉트
        flash("프로필이 이미 존재합니다. 수정 페이지로 이동합니다.")
        return redirect(url_for('main.profile_edit'))

    job_list = JobsInfo.query.with_entities(JobsInfo.job).distinct().order_by(JobsInfo.job).all()
    job_list = [job[0] for job in job_list if job[0]]

    next_page = request.args.get('next')  # ✅ 추가

    if request.method == 'POST':
        profile = UserProfile(
            user_id=session['user_id'],
            mbti=request.form.get('mbti'),
            grade_avg=request.form.get('grade_avg'),
            interest_tags=request.form.get('interest_tags'),
            favorite_subjects=request.form.get('favorite_subjects'),
            soft_skills=request.form.get('soft_skills'),
            target_career=request.form.get('target_career'),
            desired_region=request.form.get('desired_region'),
            desired_university_type=request.form.get('desired_university_type'),
            activities=request.form.get('activities'),
        )
        db.session.add(profile)
        db.session.commit()
        flash("프로필이 저장되었습니다.")

        # ✅ 저장 후 next 파라미터가 있으면 그쪽으로 이동
        if next_page == 'recommend_ai':
            return redirect(url_for('main.recommend_ai'))
        else:
            return redirect(url_for('main.profile'))

    # 빈 프로필 폼 제공 (profile=None)
    return render_template('profile_setup.html', profile=None, job_list=job_list, next_page=next_page, **get_template_context())

@main_bp.route('/profile/edit', methods=['GET', 'POST'])
def profile_edit():
    if 'user_id' not in session:
        flash("로그인 후 이용해주세요.")
        return redirect(url_for('main.login'))

    profile = UserProfile.query.filter_by(user_id=session['user_id']).first()
    if not profile:
        flash("프로필이 없습니다. 먼저 작성해주세요.")
        return redirect(url_for('main.profile_setup'))

    # 직업 목록 불러오기
    job_list = JobsInfo.query.with_entities(JobsInfo.job).distinct().order_by(JobsInfo.job).all()
    job_list = [job[0] for job in job_list if job[0]]

    if request.method == 'POST':
        profile.mbti = request.form.get('mbti')
        profile.grade_avg = request.form.get('grade_avg')
        profile.interest_tags = request.form.get('interest_tags')
        profile.favorite_subjects = request.form.get('favorite_subjects')
        profile.soft_skills = request.form.get('soft_skills')
        profile.target_career = request.form.get('target_career')
        profile.desired_region = request.form.get('desired_region')
        profile.desired_university_type = request.form.get('desired_university_type')
        profile.activities = request.form.get('activities')

        db.session.commit()
        flash("프로필이 수정되었습니다.")
        return redirect(url_for('main.profile'))

    return render_template('profile_edit.html', profile=profile, job_list=job_list, **get_template_context())


@main_bp.route('/recommend')
def recommend():
    return render_template('recommend.html', **get_template_context())


# 나머지 라우트 함수 (위의 패턴 적용)
@main_bp.route('/recommend/ai', methods=['GET', 'POST'])
def recommend_ai():
    if 'user_id' not in session:
        flash("로그인이 필요합니다.")
        return redirect(url_for('main.login'))

    profile = UserProfile.query.filter_by(user_id=session['user_id']).first()

    if not profile:
        flash("AI 분석을 위해 먼저 프로필을 작성해주세요.")
        return redirect(url_for('main.profile_setup', next='recommend_ai'))

    questions = [
        "당신의 경험과 특성을 요약해 주세요.",
        "당신이 희망하는 진로에 맞춘 준비 전략이 궁금합니다.",
        "당신에게 적합한 학과나 대학을 추천해주세요."
    ]

    if request.method == 'POST':
        try:
            answers = [request.form.get(f"answer{i+1}") for i in range(3)]
            types = ["요약", "진로", "학과"]

            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = [
                    executor.submit(get_gpt_answer, i, types[i], profile, answers[i])
                    for i in range(3)
                ]
                results = [f.result() for f in as_completed(futures)]

            result_text = "\n\n".join([f"Q{i+1}. {results[i]}" for i in range(3)])

            ai_result = AiResult(user_id=session['user_id'], result=result_text)
            db.session.add(ai_result)
            db.session.commit()

            return redirect(url_for('main.recommend_result', result_id=ai_result.id))

        except Exception as e:
            logging.error("❌ AI 분석 중 예외 발생: %s", traceback.format_exc())
            flash("AI 분석 중 오류가 발생했습니다.")
            return redirect(url_for('main.recommend_ai'))

    return render_template("recommend_ai.html", profile=profile, questions=questions, **get_template_context())

@main_bp.route('/recommend/result')
def recommend_result():
    if 'user_id' not in session:
        flash("로그인이 필요합니다.")
        return redirect(url_for('main.login'))
        
    result_id = request.args.get('result_id')
    ai_result = AiResult.query.filter_by(id=result_id, user_id=session['user_id']).first()
    if not ai_result:
        flash("결과를 찾을 수 없습니다.")
        return redirect(url_for('main.recommend_ai'))
    return render_template('recommend_result.html', result=ai_result.result, **get_template_context())

@main_bp.route('/history')
def history():
    if 'user_id' not in session:
        flash("로그인이 필요합니다.")
        return redirect(url_for('main.login'))

    results = AiResult.query.filter_by(user_id=session['user_id']).order_by(AiResult.created_at.desc()).all()
    return render_template("history.html", results=results, **get_template_context())


@main_bp.route('/vision/plan', methods=['GET', 'POST'])
def vision_plan():
    if 'user_id' not in session:
        flash("로그인 후 이용해주세요.")
        return redirect(url_for('main.login'))

    if request.method == 'POST':
        goal = request.form.get('goal')
        age = int(request.form.get('age'))
        year = request.form.get('year')
        army = request.form.get('army')

        # ✅ 군 복무 반영 로직
        if age < 18 or '고등학교' in year:
            army_info = "군 복무는 현재 고려하지 않아도 됩니다."
        else:
            if army == "가는 편이다":
                army_info = "군 복무 예정이므로 복무 기간(약 1년 6개월~2년)은 온라인 학습, 자격증 준비 등에 활용하세요."
            else:
                army_info = "군 복무 계획이 없으므로 바로 진학 또는 취업 준비를 하세요."

        # ✅ GPT 프롬프트 구성
        prompt = f"""
당신은 학생 맞춤형 커리어 플랜을 현실적으로 설계하는 전문가입니다.

[사용자 정보]
- 목표: {goal}
- 현재 나이: {age}세
- 현재 학년/상태: {year}
- 군 복무 관련: {army_info}

[요청사항]
- 학생의 현재 학년과 나이를 반영하여 현실적이고 자연스러운 커리어 플랜을 세우세요.
- 중학생은 기초 학습 위주, 고등학생은 비교과 활동과 진학 준비를, 대학생 이상은 전공 심화 및 취업 준비를 중심으로 계획하세요.
- 군 복무가 필요한 경우에는 적절한 시기에 반영하세요.
- **1년 차: ~**, **2년 차: ~** 이런 식으로 연차별 구분해서 작성하세요.
- 1년 차부터 5년 차까지 연차별 목표를 자연스러운 문단 설명 형식으로 제시하세요.
- 전체 분량은 간결하게 7~9문장 이내로 작성하세요.
"""

        import openai
        import re

        openai.api_key = os.getenv("OPENAI_API_KEY")

        try:
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "너는 현실적이고 간결한 문단형 커리어 플랜 전문가야."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=700
            )
            plan_text = response['choices'][0]['message']['content']

            # ✅ 연차별로 분리하고, 마크다운 **굵은 글씨** 제거
            plan_lines = plan_text.split('\n')
            plan_steps = []
            for line in plan_lines:
                clean_line = line.strip()
                if clean_line:
                    clean_line = re.sub(r'\*\*(.*?)\*\*', r'\1', clean_line)  # **텍스트** → 텍스트
                    plan_steps.append(clean_line)

        except Exception as e:
            plan_steps = [f"AI 호출 중 오류가 발생했습니다: {str(e)}"]

        return render_template('vision_plan_result.html', plan_steps=plan_steps, goal=goal)

    return render_template('vision_plan.html', **get_template_context())


# 캐릭터 챗
# 💬 캐릭터 코드 ↔ 한글 이름 매핑
character_name_mapping = {
    "hanul": "하늘",
    "jihan": "지한",
    "isol": "이솔"
}

# 캐릭터 선택 화면
@main_bp.route('/chat/character/select')
def select_character():
    if 'user_id' not in session:
        flash("로그인 후 이용해주세요.")
        return redirect(url_for('main.login'))
    
    return render_template('character_select.html', **get_template_context())

# 캐릭터 채팅 화면 열기
@main_bp.route('/chat/character/chat', methods=['GET'])
def character_chat():
    character_code = request.args.get('character')  # 이제 'hanul', 'jihan' 같은 코드가 옴
    character_display_name = character_name_mapping.get(character_code, "알 수 없는 캐릭터")
    return render_template('character_chat.html', character_code=character_code, character_display_name=character_display_name, **get_template_context())


# LLM 호출 함수
def call_llm_api(prompt):
    openai.api_key = os.getenv("OPENAI_API_KEY")
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "너는 학생 고민 상담을 돕는 캐릭터야."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.8,
        max_tokens=200
    )
    return response['choices'][0]['message']['content'].strip()

# 캐릭터 첫 인사말 API
@main_bp.route('/chat/character/get_greeting', methods=['POST'])
def get_character_greeting():
    data = request.json
    character_code = data.get('character', '')

    greeting = generate_greeting(character_code)

    return jsonify({"greeting": greeting})

# 캐릭터 메시지 보내는 API
@main_bp.route('/chat/character/send_message', methods=['POST'])
def send_message():
    data = request.get_json()
    character_code = data.get('character')  # 'hanul', 'jihan', 'isol'
    question = data.get('question')
    retrieved_conversations = data.get('retrieved_conversations', [])

    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "로그인이 필요합니다."}), 401

    try:
        openai.api_key = os.getenv("OPENAI_API_KEY")

        prompt = build_prompt(character_code, question, retrieved_conversations)

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "너는 학생 고민 상담 전문 캐릭터야."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )

        character_response = response['choices'][0]['message']['content']

        # ✅ user_id, character_code를 저장
        chat_log = CharacterChatHistory(
            user_id=user_id,
            character_name=character_code,  # hanul, jihan, isol 형태로 저장
            user_message=question,
            character_response=character_response
        )
        db.session.add(chat_log)
        db.session.commit()

        return jsonify({"response": character_response})

    except Exception as e:
        logging.error("❌ 캐릭터 메시지 송수신 실패: %s", traceback.format_exc())
        return jsonify({"error": "서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."}), 500


# 캐릭터 대화 히스토리 조회 화면
@main_bp.route('/chat/character/history/<character_name>', methods=['GET'])
def character_chat_history(character_name):
    # 최근 50개까지만 조회 (너가 원하는 만큼 조정 가능)
    histories = CharacterChatHistory.query.filter_by(character_name=character_name).order_by(CharacterChatHistory.timestamp.asc()).limit(50).all()
    return render_template('character_history.html', character_name=character_name, histories=histories, **get_template_context())

