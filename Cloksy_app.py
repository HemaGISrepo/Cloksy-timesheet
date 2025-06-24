import streamlit as st
import sqlite3
import pandas as pd
import io
from datetime import datetime, timedelta

# --- Database Setup ---
conn = sqlite3.connect('cloksy.db', check_same_thread=False)
c = conn.cursor()

c.execute('''
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  client TEXT,
  department TEXT,
  status TEXT DEFAULT 'active'
)''')
c.execute('''
CREATE TABLE IF NOT EXISTS time_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT,
  department TEXT,
  project TEXT,
  date TEXT,
  hours REAL,
  notes TEXT
)''')
c.execute('''
CREATE TABLE IF NOT EXISTS holidays (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT,
  date TEXT,
  type TEXT
)''')
c.execute('''
CREATE TABLE IF NOT EXISTS pto_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT,
  from_date TEXT,
  to_date TEXT,
  reason TEXT,
  status TEXT DEFAULT 'Pending',
  submitted_on TEXT
)''')
conn.commit()

# --- Page Setup ---
st.set_page_config(page_title="Cloksy Live", layout="wide")
st.title("🕒 Cloksy – Production Tracker Tool")

# --- Authentication ---
email = st.text_input("Enter your email:", placeholder="you@axial.energy")
if not email:
    st.stop()
if not email.endswith("@axial.energy"):
    st.error("Please use a valid @axial.energy email.")
    st.stop()
is_admin = email.startswith("admin@")
is_tl = "-tl@" in email

# --- Admin / TL Sidebar Controls ---
if is_admin or is_tl:
    with st.sidebar:
        st.subheader("🛠 Manage Projects & Dates / PTO")
        # Project Form
        with st.form("project_form"):
            pn = st.text_input("Project Name")
            cl = st.text_input("Client")
            dp = st.text_input("Department")
            stx = st.selectbox("Status", ["active", "inactive"])
            if st.form_submit_button("Save Project") and pn and dp:
                c.execute(
                    "INSERT INTO projects (name, client, department, status) VALUES (?, ?, ?, ?)",
                    (pn, cl, dp, stx),
                )
                conn.commit()
                st.success("Saved.")

        st.markdown("---")
        # PTO / Date Form
        st.subheader("📅 Holiday / Event / PTO Options")
        with st.form("date_form"):
            title = st.text_input("Title")
            type_sel = st.selectbox("Type", ["holiday (single/multi)", "event (range)"])
            if type_sel.startswith("holiday"):
                sel_dates = st.multiselect(
                    "Select date(s):",
                    [d.strftime("%Y-%m-%d") for d in pd.date_range(datetime.today(), periods=365)],
                )
            else:
                dt0, dt1 = st.date_input("From / To", [datetime.today(), datetime.today() + timedelta(days=1)])
                sel_dates = [d.strftime("%Y-%m-%d") for d in pd.date_range(dt0, dt1)]
            if st.form_submit_button("Save"):
                for d in sel_dates:
                    c.execute("INSERT INTO holidays (title, date, type) VALUES (?, ?, ?)",
                              (title, d, "event" if "event" in type_sel else "holiday"))
                conn.commit()
                st.success("Saved.")

        st.markdown("---")
        # PTO Approvals
        st.subheader("🔒 Pending PTO Approvals")
        df_pto = pd.read_sql("SELECT * FROM pto_requests WHERE status='Pending'", conn)
        for _, r in df_pto.iterrows():
            with st.expander(f"{r.email} {r.from_date}→{r.to_date}"):
                st.write(r.reason)
                if st.button("Approve", key=f"a{r.id}"):
                    c.execute("UPDATE pto_requests SET status='Approved' WHERE id=?", (r.id,))
                    conn.commit()
                    st.success("Approved")
                if st.button("Reject", key=f"r{r.id}"):
                    c.execute("UPDATE pto_requests SET status='Rejected' WHERE id=?", (r.id,))
                    conn.commit()
                    st.error("Rejected")

# --- Timesheet Entry for Department --
departments = [r[0] for r in c.execute("SELECT DISTINCT department FROM projects")]
selected_dept = st.selectbox("Department", departments) if departments else None

if selected_dept:
    st.subheader(f"📋 Timesheet – {selected_dept}")
    mon = datetime.today() - timedelta(days=datetime.today().weekday())
    days = [(mon + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]
    labels = [(mon + timedelta(days=i)).strftime("%a %d") for i in range(5)]
    projs = pd.read_sql(
        "SELECT name FROM projects WHERE department=? AND status='active'",
        conn, params=(selected_dept,),
    )["name"].tolist()
    projs += ["Paid Time Off", "Company Holiday", "Company Event"]
    entries = []

    for p in projs:
        rd = {"project": p}
        cols = st.columns(5)
        for i, col in enumerate(cols):
            with col:
                rd[days[i]] = st.number_input(f"{p} – {labels[i]}", min_value=0.0, step=0.25, key=f"{p}_{i}")
        entries.append(rd)

    if st.button("Save Timesheet"):
        for e in entries:
            for d in days:
                if e[d] > 0:
                    c.execute(
                        "INSERT INTO time_logs (email, department, project, date, hours, notes) VALUES (?, ?, ?, ?, ?, '')",
                        (email, selected_dept, e["project"], d, e[d]),
                    )
        conn.commit()
        st.success("Saved!")

# --- PTO Request by Employees ---
st.subheader("🧾 Request Paid Time Off")
with st.form("pto_form"):
    f = st.date_input("From")
    t = st.date_input("To")
    r = st.text_input("Reason")
    if st.form_submit_button("Submit PTO"):
        c.execute(
            "INSERT INTO pto_requests (email, from_date, to_date, reason, submitted_on) VALUES (?, ?, ?, ?, ?)",
            (email, f.strftime("%Y-%m-%d"), t.strftime("%Y-%m-%d"), r, datetime.today().strftime("%Y-%m-%d")),
        )
        conn.commit()
        st.success("Submitted")

# --- Display Holidays this Month ---
st.markdown("### 📌 Company Dates This Month")
df_h = pd.read_sql("SELECT * FROM holidays WHERE date LIKE ?", conn, params=(datetime.today().strftime("%Y-%m") + "%",))
for _, r in df_h.iterrows():
    st.info(f"{r.date} – {r.title} ({r.type})")

# --- Summary & Exports ---
st.subheader("📊 Weekly Summary")
df_l = pd.read_sql("SELECT * FROM time_logs WHERE email=? ORDER BY date DESC", conn, params=(email,))
df_l["date"] = pd.to_datetime(df_l["date"])
last_week = datetime.today() - timedelta(days=7)
df_w = df_l[df_l["date"] >= last_week]

if df_w.empty:
    st.info("No data this week.")
else:
    st.markdown("#### 📌 Project Totals (this week)")
    proj_tot = df_w.groupby("project")["hours"].sum().reset_index()
    st.dataframe(proj_tot, use_container_width=True)

    # Export CSV/Excel
    csv = proj_tot.to_csv(index=False).encode("utf-8")
    st.download_button("Download Project Summary CSV", csv, "project_summary.csv", "text/csv")
    xls = io.BytesIO()
    with pd.ExcelWriter(xls, engine="xlsxwriter") as w:
        proj_tot.to_excel(w, index=False, sheet_name="Summary")
    xls.seek(0)
    st.download_button("Download Project Summary XLSX", xls, "project_summary.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # Per-employee breakdown
    st.markdown("#### 📋 Employee Breakdown")
    emp_sel = st.selectbox("Employee", ["All"] + sorted(df_w.email.unique()))
    vet = df_w[df_w["email"] == emp_sel] if emp_sel != "All" else df_w
    for emp in (vet.email.unique() if emp_sel == "All" else [emp_sel]):
        st.write(f"---\n#### {emp}")
        sub = df_w[df_w["email"] == emp].copy()
        sub["day"] = sub["date"].dt.day_name()
        piv = sub.pivot_table(index="day", columns="project", values="hours", aggfunc="sum", fill_value=0)
        piv = piv.reindex([*["Monday","Tuesday","Wednesday","Thursday","Friday"]], fill_value=0)
        piv["Total Hours"] = piv.sum(axis=1)
        st.dataframe(piv)

    # Dept-level view
    st.markdown("#### 🏢 Department Breakdown")
    if "department" in df_w.columns:
        w = df_w.copy()
        w["day"] = w["date"].dt.day_name()
        dg = w.groupby(["department", "day", "project"])["hours"].sum().reset_index()
        for d_ in dg.department.unique():
            st.write("---\n### 🧑‍💼 Dept:", d_)
            dd = dg[dg.department == d_]
            piv = dd.pivot_table(index="day", columns="project", values="hours", aggfunc="sum", fill_value=0)
            piv = piv.reindex(["Monday","Tuesday","Wednesday","Thursday","Friday"], fill_value=0)
            piv["Total"] = piv.sum(axis=1)
            st.dataframe(piv)

        dept_csv = dg.to_csv(index=False).encode("utf-8")
        st.download_button("Download Dept Breakdown CSV", dept_csv, "dept_breakdown.csv", "text/csv")
