import datetime
import calendar
import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from dateutil import parser as date_parser
from dotenv import load_dotenv

load_dotenv("secrets.env")

from llm_client import call_scheduler_llm
from model_selection import apply_model_selection, current_available_models, update_override

app = Flask(__name__)
app.config['SECRET_KEY'] = 'devkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///scheduler.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Models

class Routine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    days = db.Column(db.String(50), default="0,1,2,3,4") # 0=Mon, 6=Sun. Comma separated
    description = db.Column(db.String(200))
    steps = db.relationship('Step', backref='routine', lazy=True, cascade="all, delete-orphan")

class Step(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    routine_id = db.Column(db.Integer, db.ForeignKey('routine.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    time = db.Column(db.String(10), default="00:00") # HH:MM
    category = db.Column(db.String(50), default="Other") # IoT, Browser, Lifestyle, Other

class DailyLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    step_id = db.Column(db.Integer, db.ForeignKey('step.id'), nullable=False)
    done = db.Column(db.Boolean, default=False)
    memo = db.Column(db.String(200))
    
    step = db.relationship('Step')

class CustomTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    time = db.Column(db.String(10), default="00:00")
    done = db.Column(db.Boolean, default=False)
    memo = db.Column(db.String(200))

class DayLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    content = db.Column(db.Text)

class ChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)

# Initialize DB
with app.app_context():
    db.create_all()

# Helpers
def get_weekday_routines(weekday_int):
    all_routines = Routine.query.all()
    matched = []
    for r in all_routines:
        if str(weekday_int) in r.days.split(','):
            matched.append(r)
    return matched

def _parse_date(value, default_date):
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            try:
                return date_parser.parse(value).date()
            except (ValueError, TypeError, OverflowError):
                return default_date
    return default_date

def _bool_from_value(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default

def _get_timeline_data(date_obj):
    routines = get_weekday_routines(date_obj.weekday())
    custom_tasks = CustomTask.query.filter_by(date=date_obj).all()
    
    timeline_items = []
    total_items = 0
    completed_items = 0

    for r in routines:
        for s in r.steps:
            log = DailyLog.query.filter_by(date=date_obj, step_id=s.id).first()
            timeline_items.append({
                'type': 'routine',
                'routine': r,
                'step': s,
                'log': log,
                'time': s.time,
                'id': s.id
            })
            total_items += 1
            if log and log.done:
                completed_items += 1
            
    for ct in custom_tasks:
        timeline_items.append({
            'type': 'custom',
            'routine': {'name': 'Personal'},
            'step': {'name': ct.name, 'category': 'Custom', 'id': ct.id},
            'log': {'done': ct.done, 'memo': ct.memo},
            'time': ct.time,
            'id': ct.id,
            'real_obj': ct
        })
        total_items += 1
        if ct.done:
            completed_items += 1
    
    timeline_items.sort(key=lambda x: x['time'])
    
    completion_rate = 0
    if total_items > 0:
        completion_rate = int((completed_items / total_items) * 100)
        
    return timeline_items, completion_rate

def _build_scheduler_context(today=None):
    today = today or datetime.date.today()
    routines = Routine.query.all()
    today_logs = {log.step_id: log for log in DailyLog.query.filter_by(date=today).all()}
    custom_tasks = CustomTask.query.filter_by(date=today).all()
    
    # Fetch recent DayLogs (Today + past 2 days)
    recent_day_logs = []
    for i in range(3):
        d = today - datetime.timedelta(days=i)
        dl = DayLog.query.filter_by(date=d).first()
        if dl and dl.content:
            recent_day_logs.append(f"Date: {d.isoformat()} | Content: {dl.content}")

    routine_lines = []
    for r in routines:
        days_label = r.days or ""
        steps = ", ".join(
            f"[{s.id}] {s.time} {s.name} ({s.category})"
            for s in sorted(r.steps, key=lambda item: item.time)
        ) or "no steps"
        routine_lines.append(f"- Routine {r.id}: {r.name} | days={days_label} | {steps}")

    custom_lines = []
    for task in sorted(custom_tasks, key=lambda t: t.time):
        memo = f" memo={task.memo}" if task.memo else ""
        custom_lines.append(
            f"- CustomTask {task.id}: {task.time} {task.name} done={task.done}{memo}"
        )

    log_lines = []
    for step_id, log in today_logs.items():
        memo = f" memo={log.memo}" if log.memo else ""
        log_lines.append(f"- StepLog step_id={step_id} done={log.done}{memo}")

    context_parts = [
        f"today_date: {today.isoformat()}",
        "routines:",
        *routine_lines,
        "today_custom_tasks:",
        *(custom_lines or ["(none)"]),
        "today_step_logs:",
        *(log_lines or ["(none)"]),
        "recent_day_logs:",
        *(recent_day_logs or ["(none)"]),
    ]
    return "\n".join(context_parts)

def _apply_actions(actions, default_date):
    results = []
    errors = []
    modified_ids = []
    dirty = False

    if not isinstance(actions, list) or not actions:
        return results, errors, modified_ids

    try:
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_type = action.get("type")

            if action_type == "create_custom_task":
                name = action.get("name")
                if not isinstance(name, str) or not name.strip():
                    errors.append("create_custom_task: name が指定されていません。")
                    continue
                date_value = _parse_date(action.get("date"), default_date)
                time_value = action.get("time") if isinstance(action.get("time"), str) else "00:00"
                memo = action.get("memo") if isinstance(action.get("memo"), str) else ""
                new_task = CustomTask(date=date_value, name=name.strip(), time=time_value.strip(), memo=memo.strip())
                db.session.add(new_task)
                db.session.flush() # Get ID
                results.append(f"カスタムタスク「{new_task.name}」を {date_value} の {new_task.time} に追加しました。")
                modified_ids.append(f"item_custom_{new_task.id}")
                dirty = True
                continue
            
            if action_type == "delete_custom_task":
                task_id = action.get("task_id")
                try:
                    task_id_int = int(task_id)
                except (TypeError, ValueError):
                    errors.append("delete_custom_task: task_id が不正です。")
                    continue
                task_obj = CustomTask.query.get(task_id_int)
                if not task_obj:
                    errors.append(f"task_id={task_id_int} が見つかりませんでした。")
                    continue
                db.session.delete(task_obj)
                results.append(f"カスタムタスク「{task_obj.name}」を削除しました。")
                # No modified ID because it's gone, but we want to refresh
                dirty = True
                continue

            if action_type == "toggle_step":
                step_id = action.get("step_id")
                try:
                    step_id_int = int(step_id)
                except (TypeError, ValueError):
                    errors.append("toggle_step: step_id が不正です。")
                    continue
                step_obj = Step.query.get(step_id_int)
                if not step_obj:
                    errors.append(f"step_id={step_id_int} が見つかりませんでした。")
                    continue
                date_value = _parse_date(action.get("date"), default_date)
                log = DailyLog.query.filter_by(date=date_value, step_id=step_obj.id).first()
                if not log:
                    log = DailyLog(date=date_value, step_id=step_obj.id)
                    db.session.add(log)
                log.done = _bool_from_value(action.get("done"), True)
                memo = action.get("memo")
                if isinstance(memo, str):
                    log.memo = memo.strip()
                results.append(
                    f"ステップ「{step_obj.name}」({date_value}) を {'完了' if log.done else '未完了'} に更新しました。"
                )
                modified_ids.append(f"item_routine_{step_obj.id}")
                dirty = True
                continue

            if action_type == "toggle_custom_task":
                task_id = action.get("task_id")
                try:
                    task_id_int = int(task_id)
                except (TypeError, ValueError):
                    errors.append("toggle_custom_task: task_id が不正です。")
                    continue
                task_obj = CustomTask.query.get(task_id_int)
                if not task_obj:
                    errors.append(f"task_id={task_id_int} が見つかりませんでした。")
                    continue
                task_obj.done = _bool_from_value(action.get("done"), True)
                memo = action.get("memo")
                if isinstance(memo, str):
                    task_obj.memo = memo.strip()
                results.append(
                    f"カスタムタスク「{task_obj.name}」を {'完了' if task_obj.done else '未完了'} に更新しました。"
                )
                modified_ids.append(f"item_custom_{task_obj.id}")
                dirty = True
                continue

            if action_type == "update_log":
                content = action.get("content")
                if not isinstance(content, str) or not content.strip():
                    errors.append("update_log: content が指定されていません。")
                    continue
                date_value = _parse_date(action.get("date"), default_date)
                day_log = DayLog.query.filter_by(date=date_value).first()
                if not day_log:
                    day_log = DayLog(date=date_value)
                    db.session.add(day_log)
                day_log.content = content.strip()
                results.append(f"{date_value} の日報を更新しました。")
                modified_ids.append("daily-log-card")
                dirty = True
                continue
            
            # Routine/Step Management
            if action_type == "add_routine":
                name = action.get("name")
                if not name:
                    errors.append("add_routine: name is required")
                    continue
                days = action.get("days", "0,1,2,3,4")
                desc = action.get("description", "")
                r = Routine(name=name, days=days, description=desc)
                db.session.add(r)
                results.append(f"ルーチン「{name}」を追加しました。")
                dirty = True
                continue
                
            if action_type == "delete_routine":
                rid = action.get("routine_id")
                r = Routine.query.get(int(rid)) if rid else None
                if r:
                    db.session.delete(r)
                    results.append(f"ルーチン「{r.name}」を削除しました。")
                    dirty = True
                else:
                    errors.append("delete_routine: not found")
                continue

            if action_type == "add_step":
                rid = action.get("routine_id")
                name = action.get("name")
                if not rid or not name:
                    errors.append("add_step: routine_id and name required")
                    continue
                s = Step(routine_id=int(rid), name=name, time=action.get("time", "00:00"), category=action.get("category", "Other"))
                db.session.add(s)
                db.session.flush()
                results.append(f"ステップ「{name}」を追加しました。")
                modified_ids.append(f"item_routine_{s.id}")
                dirty = True
                continue

            if action_type == "delete_step":
                sid = action.get("step_id")
                s = Step.query.get(int(sid)) if sid else None
                if s:
                    db.session.delete(s)
                    results.append(f"ステップ「{s.name}」を削除しました。")
                    dirty = True
                else:
                    errors.append("delete_step: not found")
                continue

            errors.append(f"未知のアクション: {action_type}")

        if dirty:
            db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        errors.append(f"操作の適用に失敗しました: {exc}")
        results = []

    return results, errors, modified_ids

@app.route('/')
def index():
    today = datetime.date.today()
    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)
    
    if month > 12:
        month = 1
        year += 1
    elif month < 1:
        month = 12
        year -= 1
        
    cal = calendar.Calendar(firstweekday=0) 
    month_days = cal.monthdatescalendar(year, month)
    
    calendar_data = []
    for week in month_days:
        week_data = []
        for day in week:
            is_current_month = (day.month == month)
            
            weekday = day.weekday()
            routines = get_weekday_routines(weekday)
            total_steps = sum(len(r.steps) for r in routines)
            
            logs = DailyLog.query.filter_by(date=day).all()
            completed_count = sum(1 for l in logs if l.done)
            
            custom_tasks = CustomTask.query.filter_by(date=day).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for t in custom_tasks if t.done)

            day_log = DayLog.query.filter_by(date=day).first()
            has_day_log = bool(day_log and day_log.content and day_log.content.strip())

            color_class = "bg-light"
            if total_steps > 0:
                ratio = completed_count / total_steps
                if ratio == 1.0:
                    color_class = "bg-success text-white"
                elif ratio > 0.5:
                    color_class = "bg-warning"
                elif ratio > 0:
                    color_class = "bg-info text-white"
            
            week_data.append({
                'date': day,
                'day_num': day.day,
                'is_current_month': is_current_month,
                'total_routines': len(routines) + len(custom_tasks),
                'total_steps': total_steps,
                'completed_steps': completed_count,
                'color_class': color_class,
                'has_day_log': has_day_log
            })
        calendar_data.append(week_data)

    return render_template('index.html', 
                           calendar_data=calendar_data, 
                           year=year, month=month,
                           today=today)

@app.route('/calendar_partial')
def calendar_partial():
    today = datetime.date.today()
    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)
    
    if month > 12:
        month = 1
        year += 1
    elif month < 1:
        month = 12
        year -= 1
        
    cal = calendar.Calendar(firstweekday=0) 
    month_days = cal.monthdatescalendar(year, month)
    
    calendar_data = []
    for week in month_days:
        week_data = []
        for day in week:
            is_current_month = (day.month == month)
            
            weekday = day.weekday()
            routines = get_weekday_routines(weekday)
            total_steps = sum(len(r.steps) for r in routines)
            
            logs = DailyLog.query.filter_by(date=day).all()
            completed_count = sum(1 for l in logs if l.done)
            
            custom_tasks = CustomTask.query.filter_by(date=day).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for t in custom_tasks if t.done)

            day_log = DayLog.query.filter_by(date=day).first()
            has_day_log = bool(day_log and day_log.content and day_log.content.strip())
            
            week_data.append({
                'date': day,
                'day_num': day.day,
                'is_current_month': is_current_month,
                'total_routines': len(routines) + len(custom_tasks),
                'total_steps': total_steps,
                'completed_steps': completed_count,
                'has_day_log': has_day_log
            })
        calendar_data.append(week_data)
    
    return render_template('calendar_partial.html', calendar_data=calendar_data, today=today)


@app.route("/embed/calendar")
def embed_calendar():
    today = datetime.date.today()
    year = request.args.get("year", today.year, type=int)
    month = request.args.get("month", today.month, type=int)

    if month > 12:
        month = 1
        year += 1
    elif month < 1:
        month = 12
        year -= 1

    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdatescalendar(year, month)

    calendar_data = []
    for week in month_days:
        week_data = []
        for day in week:
            is_current_month = day.month == month
            weekday = day.weekday()
            routines = get_weekday_routines(weekday)
            total_steps = sum(len(r.steps) for r in routines)

            logs = DailyLog.query.filter_by(date=day).all()
            completed_count = sum(1 for l in logs if l.done)

            custom_tasks = CustomTask.query.filter_by(date=day).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for t in custom_tasks if t.done)

            day_log = DayLog.query.filter_by(date=day).first()
            has_day_log = bool(day_log and day_log.content and day_log.content.strip())

            color_class = "bg-light"
            if total_steps > 0:
                ratio = completed_count / total_steps
                if ratio == 1.0:
                    color_class = "bg-success text-white"
                elif ratio > 0.5:
                    color_class = "bg-warning"
                elif ratio > 0:
                    color_class = "bg-info text-white"

            week_data.append(
                {
                    "date": day,
                    "day_num": day.day,
                    "is_current_month": is_current_month,
                    "total_routines": len(routines) + len(custom_tasks),
                    "total_steps": total_steps,
                    "completed_steps": completed_count,
                    "color_class": color_class,
                    "has_day_log": has_day_log,
                }
            )
        calendar_data.append(week_data)

    return render_template(
        "embed_calendar.html",
        calendar_data=calendar_data,
        year=year,
        month=month,
        today=today,
    )


@app.route('/day/<date_str>', methods=['GET', 'POST'])
def day_view(date_str):
    try:
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        if 'add_custom_task' in request.form:
            name = request.form.get('custom_name')
            time = request.form.get('custom_time')
            if name:
                ct = CustomTask(date=date_obj, name=name, time=time)
                db.session.add(ct)
                db.session.commit()
                flash('カスタムタスクを追加しました。')
            return redirect(url_for('day_view', date_str=date_str))

        if 'save_log' in request.form:
            content = request.form.get('day_log_content')
            dlog = DayLog.query.filter_by(date=date_obj).first()
            if not dlog:
                dlog = DayLog(date=date_obj)
                db.session.add(dlog)
            dlog.content = content
            db.session.commit()
            flash('日報を保存しました。')
            return redirect(url_for('day_view', date_str=date_str))

        if 'delete_custom_task' in request.form:
            task_id = request.form.get('delete_custom_task')
            task = CustomTask.query.get(task_id)
            if task:
                db.session.delete(task)
                db.session.commit()
                flash('タスクを削除しました。')
            return redirect(url_for('day_view', date_str=date_str))

        # Update Steps and Custom Tasks
        routines = get_weekday_routines(date_obj.weekday())
        all_steps = []
        for r in routines:
            all_steps.extend(r.steps)
            
        for step in all_steps:
            done_key = f"done_{step.id}"
            memo_key = f"memo_{step.id}"
            is_done = (request.form.get(done_key) == 'on')
            memo_text = request.form.get(memo_key, '')
            
            log = DailyLog.query.filter_by(date=date_obj, step_id=step.id).first()
            if not log:
                log = DailyLog(date=date_obj, step_id=step.id)
                db.session.add(log)
            
            log.done = is_done
            log.memo = memo_text
        
        custom_tasks = CustomTask.query.filter_by(date=date_obj).all()
        for task in custom_tasks:
            done_key = f"custom_done_{task.id}"
            memo_key = f"custom_memo_{task.id}"
            is_done = (request.form.get(done_key) == 'on')
            memo_text = request.form.get(memo_key, '')
            task.done = is_done
            task.memo = memo_text

        db.session.commit()
        flash('進捗を保存しました。')
        return redirect(url_for('day_view', date_str=date_str))

    # GET
    timeline_items, completion_rate = _get_timeline_data(date_obj)
    day_log = DayLog.query.filter_by(date=date_obj).first()
    
    return render_template('day.html', date=date_obj, timeline_items=timeline_items, day_log=day_log, completion_rate=completion_rate)

@app.route('/day/<date_str>/timeline')
def day_view_timeline(date_str):
    try:
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return "Invalid Date", 400
    
    timeline_items, completion_rate = _get_timeline_data(date_obj)
    # Note: day_log is not used in timeline_partial strictly, but might be if we updated that too. 
    # timeline_partial only uses timeline_items and date/completion_rate.
    
    return render_template('timeline_partial.html', date=date_obj, timeline_items=timeline_items, completion_rate=completion_rate)

@app.route('/day/<date_str>/log_partial')
def day_view_log_partial(date_str):
    try:
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return "Invalid Date", 400
    
    day_log = DayLog.query.filter_by(date=date_obj).first()
    return render_template('log_partial.html', day_log=day_log)


@app.route('/routines')
def routines_list():
    routines = Routine.query.all()
    return render_template('routines.html', routines=routines)

@app.route('/routines/add', methods=['POST'])
def add_routine():
    name = request.form.get('name')
    days = ",".join(request.form.getlist('days'))
    desc = request.form.get('description')
    if name:
        r = Routine(name=name, days=days, description=desc)
        db.session.add(r)
        db.session.commit()
    return redirect(url_for('routines_list'))

@app.route('/routines/<int:id>/delete', methods=['POST'])
def delete_routine(id):
    r = Routine.query.get_or_404(id)
    db.session.delete(r)
    db.session.commit()
    return redirect(url_for('routines_list'))

@app.route('/routines/<int:id>/step/add', methods=['POST'])
def add_step(id):
    r = Routine.query.get_or_404(id)
    name = request.form.get('name')
    time = request.form.get('time')
    category = request.form.get('category')
    if name:
        s = Step(routine_id=r.id, name=name, time=time, category=category)
        db.session.add(s)
        db.session.commit()
    return redirect(url_for('routines_list'))

@app.route('/steps/<int:id>/delete', methods=['POST'])
def delete_step(id):
    s = Step.query.get_or_404(id)
    db.session.delete(s)
    db.session.commit()
    return redirect(url_for('routines_list'))

@app.get("/api/models")
def list_models():
    provider, model, base_url, _ = apply_model_selection("scheduler")
    return jsonify(
        {
            "models": current_available_models(),
            "current": {"provider": provider, "model": model, "base_url": base_url},
        }
    )

@app.post("/model_settings")
def update_model_settings():
    payload = request.get_json(silent=True) or {}
    selection = payload.get("selection") if "selection" in payload else payload
    if isinstance(selection, dict) and "scheduler" in selection:
        selection = selection.get("scheduler")
    if selection is not None and not isinstance(selection, dict):
        return jsonify({"error": "selection must be an object"}), 400

    try:
        provider, model, base_url, _ = update_override(selection if selection else None)
    except Exception as exc:
        return jsonify({"error": f"モデル設定の更新に失敗しました: {exc}"}), 500
    return jsonify({"status": "ok", "applied": {"provider": provider, "model": model, "base_url": base_url}})

@app.route("/api/chat/history", methods=["GET", "DELETE"])
def manage_chat_history():
    if request.method == "DELETE":
        try:
            ChatHistory.query.delete()
            db.session.commit()
            return jsonify({"status": "cleared"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
    
    # GET
    history = ChatHistory.query.order_by(ChatHistory.timestamp).all()
    return jsonify({
        "history": [
            {"role": h.role, "content": h.content, "timestamp": h.timestamp.isoformat()}
            for h in history
        ]
    })

@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        return jsonify({"error": "messages must be a list"}), 400

    formatted_messages = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            continue
        formatted_messages.append({"role": role, "content": content})

    if not formatted_messages or formatted_messages[-1]["role"] != "user":
        return jsonify({"error": "last message must be from user"}), 400

    # Save user message
    user_msg_content = formatted_messages[-1]["content"]
    try:
        db.session.add(ChatHistory(role="user", content=user_msg_content))
        db.session.commit()
    except Exception as e:
        print(f"Failed to save user message: {e}")

    today = datetime.date.today()
    context = _build_scheduler_context(today)

    try:
        reply_text, actions = call_scheduler_llm(formatted_messages, context)
    except Exception as exc:
        return jsonify({"reply": f"LLM 呼び出しに失敗しました: {exc}"}), 200

    results, errors, modified_ids = _apply_actions(actions, today)

    message_parts = []
    if reply_text and reply_text.strip():
        message_parts.append(reply_text.strip())
    if results:
        message_parts.append("実行結果:\n" + "\n".join(f"- {item}" for item in results))
    if errors:
        message_parts.append("処理で問題が発生しました:\n" + "\n".join(f"- {err}" for err in errors))

    final_reply = "\n\n".join(message_parts) if message_parts else "了解しました。"

    # Save assistant reply
    try:
        db.session.add(ChatHistory(role="assistant", content=final_reply))
        db.session.commit()
    except Exception as e:
        print(f"Failed to save assistant message: {e}")
    
    # Return JSON with extra fields
    return jsonify({
        "reply": final_reply,
        "should_refresh": (len(results) > 0),
        "modified_ids": modified_ids
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5010, debug=True)
