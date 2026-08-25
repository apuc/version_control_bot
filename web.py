"""
Веб-интерфейс для управления мониторингом репозиториев.

Запуск:
    python web.py
"""

from flask import Flask, render_template, request, redirect, url_for, flash
import database as db
from config import config

app = Flask(__name__)
app.secret_key = config.web_secret_key


@app.before_request
def _ensure_db():
    db.init_db()


# ---- Репозитории ----

@app.route("/")
def index():
    repos = db.list_repos()
    return render_template("index.html", repos=repos)


@app.route("/repo/add", methods=["GET", "POST"])
def repo_add():
    if request.method == "POST":
        name = request.form["name"].strip()
        path = request.form["path"].strip()
        branch = request.form.get("branch", "main").strip() or "main"
        interval = int(request.form.get("poll_interval", 30))
        enabled = "enabled" in request.form

        if not name or not path:
            flash("Название и путь обязательны.", "error")
            return redirect(url_for("repo_add"))

        db.add_repo(name=name, path=path, branch=branch,
                    poll_interval=interval, enabled=enabled)
        flash(f"Репозиторий «{name}» добавлен.", "success")
        return redirect(url_for("index"))

    return render_template("repo_form.html", repo=None)


@app.route("/repo/<int:repo_id>")
def repo_detail(repo_id):
    repo = db.get_repo(repo_id)
    if not repo:
        flash("Репозиторий не найден.", "error")
        return redirect(url_for("index"))

    bindings = db.list_bindings(repo_id=repo_id)
    return render_template("repo_detail.html", repo=repo, bindings=bindings)


@app.route("/repo/<int:repo_id>/edit", methods=["GET", "POST"])
def repo_edit(repo_id):
    repo = db.get_repo(repo_id)
    if not repo:
        flash("Репозиторий не найден.", "error")
        return redirect(url_for("index"))

    if request.method == "POST":
        db.update_repo(
            repo_id,
            name=request.form["name"].strip(),
            path=request.form["path"].strip(),
            branch=request.form.get("branch", "main").strip() or "main",
            poll_interval=int(request.form.get("poll_interval", 30)),
            enabled="enabled" in request.form,
        )
        flash("Репозиторий обновлён.", "success")
        return redirect(url_for("repo_detail", repo_id=repo_id))

    return render_template("repo_form.html", repo=repo)


@app.route("/repo/<int:repo_id>/delete", methods=["POST"])
def repo_delete(repo_id):
    repo = db.get_repo(repo_id)
    if repo:
        db.delete_repo(repo_id)
        flash(f"Репозиторий «{repo.name}» удалён.", "success")
    return redirect(url_for("index"))


# ---- Привязки чатов ----

@app.route("/repo/<int:repo_id>/binding/add", methods=["POST"])
def binding_add(repo_id):
    repo = db.get_repo(repo_id)
    if not repo:
        flash("Репозиторий не найден.", "error")
        return redirect(url_for("index"))

    chat_id = request.form["chat_id"].strip()
    chat_title = request.form.get("chat_title", "").strip()

    if not chat_id:
        flash("Chat ID обязателен.", "error")
        return redirect(url_for("repo_detail", repo_id=repo_id))

    db.add_binding(repo_id=repo_id, chat_id=chat_id, chat_title=chat_title)
    flash(f"Чат «{chat_title or chat_id}» привязан.", "success")
    return redirect(url_for("repo_detail", repo_id=repo_id))


@app.route("/binding/<int:binding_id>/delete", methods=["POST"])
def binding_delete(binding_id):
    # Узнаём repo_id перед удалением
    bindings = db.list_bindings()
    repo_id = None
    for b in bindings:
        if b.id == binding_id:
            repo_id = b.repo_id
            break

    db.delete_binding(binding_id)
    flash("Привязка удалена.", "success")

    if repo_id is not None:
        return redirect(url_for("repo_detail", repo_id=repo_id))
    return redirect(url_for("index"))


# ---- Запуск ----

if __name__ == "__main__":
    db.init_db()
    app.run(host=config.web_host, port=config.web_port, debug=True)
