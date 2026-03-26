import csv
import io
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, Response, url_for

from dcc_tracker import config as cfg
from dcc_tracker import tracker

app = Flask(__name__)
app.secret_key = "dcc-tracker-local"


@app.template_filter("format_int")
def format_int(value):
    return f"{int(value):,}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_all():
    """Load and return (state, all_orchs, sr_registry)."""
    config_orchs = tracker.load_orchestrations(cfg.get_config_path())
    state = tracker.load_state(cfg.get_state_path())
    all_orchs = tracker.merge_orchestrations(config_orchs, state["orchestration_overrides"])
    sr_registry = tracker.load_sr_registry(cfg.get_sr_registry_path())
    return state, all_orchs, sr_registry


def _save(state):
    tracker.save_state(state, cfg.get_state_path())


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    state, all_orchs, sr_registry = _load_all()
    # Build display rows
    rows = []
    for name in sorted(all_orchs):
        sr_map = all_orchs[name]
        sr_display = [
            {"code": code, "name": sr_registry.get(code, code), "count": cnt}
            for code, cnt in sorted(sr_map.items())
        ]
        rows.append({
            "name": name,
            "sr": sr_display,
            "estimate": state["estimates"].get(name, 0),
            "actual": state["actual_counts"].get(name, 0),
            "is_custom": name in state["orchestration_overrides"],
        })
    estimates_set = sum(1 for r in rows if r["estimate"] > 0)
    return render_template(
        "dashboard.html",
        rows=rows,
        estimates_set=estimates_set,
        total_orchs=len(rows),
    )


@app.route("/set-estimate", methods=["POST"])
def set_estimate():
    data = request.get_json()
    orch_name = data.get("orchestration")
    try:
        estimated_runs = int(data.get("estimated_runs", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "estimated_runs must be an integer"}), 400

    state, all_orchs, _ = _load_all()
    try:
        tracker.set_estimate(state, orch_name, estimated_runs, all_orchs)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    _save(state)
    return jsonify({"ok": True, "estimate": estimated_runs})


@app.route("/log-run", methods=["POST"])
def log_run():
    data = request.get_json()
    orch_name = data.get("orchestration")
    try:
        count = int(data.get("count", 1))
    except (TypeError, ValueError):
        return jsonify({"error": "count must be an integer"}), 400

    state, all_orchs, _ = _load_all()
    try:
        tracker.log_run(state, orch_name, all_orchs, count=count)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    _save(state)
    return jsonify({"ok": True, "actual": state["actual_counts"][orch_name]})


@app.route("/report")
def report():
    state, all_orchs, sr_registry = _load_all()
    sr_totals = tracker.calculate_sr_totals(all_orchs, state["estimates"], sr_registry)
    thresholds = tracker.calculate_thresholds(sr_totals)
    rows = tracker.build_report_rows(sr_totals, thresholds, sr_registry)
    non_zero = sum(1 for r in rows if r["Total Estimated Requests"] > 0)
    return render_template("report.html", rows=rows, non_zero=non_zero, total=len(rows))


@app.route("/report/download")
def report_download():
    state, all_orchs, sr_registry = _load_all()
    sr_totals = tracker.calculate_sr_totals(all_orchs, state["estimates"], sr_registry)
    thresholds = tracker.calculate_thresholds(sr_totals)
    rows = tracker.build_report_rows(sr_totals, thresholds, sr_registry)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=tracker.REPORT_FIELDNAMES)
    writer.writeheader()
    writer.writerows(rows)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=adt_thresholds.csv"},
    )


@app.route("/add-orchestration", methods=["GET", "POST"])
def add_orchestration():
    _, _, sr_registry = _load_all()
    sr_options = sorted(
        [{"code": code, "name": name} for code, name in sr_registry.items()],
        key=lambda x: x["code"],
    )

    if request.method == "POST":
        orch_name = request.form.get("orchestration_name", "").strip()
        codes = request.form.getlist("sr_code")
        counts = request.form.getlist("sr_count")

        if not orch_name:
            flash("Orchestration name is required.", "danger")
            return render_template("add_orchestration.html", sr_options=sr_options)

        sr_counts = {}
        errors = []
        for code, count_str in zip(codes, counts):
            code = code.strip()
            if not code:
                continue
            try:
                cnt = int(count_str)
                if cnt < 1:
                    raise ValueError
            except (ValueError, TypeError):
                errors.append(f"Count for {code!r} must be a positive integer.")
                continue
            sr_counts[code] = cnt

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template("add_orchestration.html", sr_options=sr_options)

        if not sr_counts:
            flash("At least one service request is required.", "danger")
            return render_template("add_orchestration.html", sr_options=sr_options)

        state, _, _ = _load_all()
        try:
            tracker.add_orchestration(state, orch_name, sr_counts)
        except ValueError as e:
            flash(str(e), "danger")
            return render_template("add_orchestration.html", sr_options=sr_options)

        _save(state)
        flash(f"Orchestration '{orch_name}' saved successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("add_orchestration.html", sr_options=sr_options)


@app.route("/delete-orchestration", methods=["POST"])
def delete_orchestration():
    orch_name = request.get_json().get("orchestration")
    state, _, _ = _load_all()
    if orch_name not in state["orchestration_overrides"]:
        return jsonify({"error": "Can only delete custom orchestrations."}), 400
    del state["orchestration_overrides"][orch_name]
    state["estimates"].pop(orch_name, None)
    state["actual_counts"].pop(orch_name, None)
    _save(state)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)
