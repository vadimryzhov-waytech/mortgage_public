import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import math

# -------------------- Функции расчёта (из консольной версии) --------------------
def format_money(value):
    return f"{value:,.2f} ₽"

class Tranche:
    def __init__(self, amount, rate):
        self.amount = amount
        self.rate = rate
        self.remaining = amount
        self.monthly_payment = None
        self.base_principal = None

class EarlyPayment:
    def __init__(self, month, amount):
        self.month = month
        self.amount = amount

class MortgageOption:
    def __init__(self, name, tranches, years, pay_type='annuity', early_payments=None,
                 renovation_start_year=None, renovation_duration=None, renovation_total_cost=None):
        self.name = name
        self.tranches = tranches
        self.years = years
        self.months = years * 12
        self.pay_type = pay_type
        self.early_payments = early_payments or []
        self.renovation_start_month = (renovation_start_year * 12 + 1) if renovation_start_year is not None else None
        self.renovation_duration = renovation_duration
        self.renovation_total_cost = renovation_total_cost

        # Инициализация платежей
        if pay_type == 'annuity':
            for t in self.tranches:
                monthly_rate = t.rate / 100 / 12
                if monthly_rate == 0:
                    t.monthly_payment = t.amount / self.months
                else:
                    coeff = (monthly_rate * (1 + monthly_rate) ** self.months) / ((1 + monthly_rate) ** self.months - 1)
                    t.monthly_payment = t.amount * coeff
        else:
            for t in self.tranches:
                t.base_principal = t.amount / self.months

    def total_principal(self):
        return sum(t.amount for t in self.tranches)

    def _apply_early_to_list(self, lines, amount):
        remaining = amount
        active = sorted([t for t in lines if t.remaining > 1e-9], key=lambda t: t.rate, reverse=True)
        for t in active:
            if remaining <= 0:
                break
            if remaining >= t.remaining:
                remaining -= t.remaining
                t.remaining = 0.0
            else:
                t.remaining -= remaining
                remaining = 0.0

    def compute_schedule(self):
        import copy
        lines = [copy.deepcopy(t) for t in self.tranches]
        early_sorted = sorted(self.early_payments, key=lambda ep: ep.month)

        payments = []
        month = 1
        total_paid = 0.0

        while any(t.remaining > 1e-9 for t in lines):
            for ep in early_sorted:
                if ep.month == month:
                    self._apply_early_to_list(lines, ep.amount)

            if self.pay_type == 'annuity':
                monthly_sum = 0.0
                for t in lines:
                    if t.remaining > 1e-9:
                        mr = t.rate / 100 / 12
                        interest = t.remaining * mr
                        max_pm = t.remaining + interest
                        actual = min(t.monthly_payment, max_pm)
                        monthly_sum += actual
                        if actual >= interest:
                            t.remaining -= (actual - interest)
                        else:
                            t.remaining = max(0, t.remaining)
            else:
                monthly_sum = 0.0
                for t in lines:
                    if t.remaining > 1e-9:
                        mr = t.rate / 100 / 12
                        interest = t.remaining * mr
                        principal = min(t.base_principal, t.remaining)
                        monthly_sum += principal + interest
                        t.remaining -= principal
            payments.append(monthly_sum)
            total_paid += monthly_sum
            month += 1
            if month > 1200:
                break

        return {
            'payments': payments,
            'total_paid': total_paid,
            'overpayment': total_paid - sum(t.amount for t in self.tranches),
            'actual_months': len(payments),
            'first': payments[0] if payments else 0,
            'last': payments[-1] if payments else 0,
            'min': min(payments) if payments else 0,
            'max': max(payments) if payments else 0,
        }

    def renovation_info(self, sched):
        if self.renovation_start_month is None:
            return None
        monthly = self.renovation_total_cost / self.renovation_duration
        start = self.renovation_start_month
        end = start + self.renovation_duration - 1
        payments = sched['payments']
        peak = 0.0
        for m in range(start, end+1):
            mortgage_pm = payments[m-1] if 1 <= m <= len(payments) else 0
            total = mortgage_pm + monthly
            peak = max(peak, total)
        return {'monthly': monthly, 'start': start, 'end': end, 'peak': peak}

# -------------------- Интерфейс Streamlit --------------------
st.set_page_config(page_title="Ипотечный калькулятор PRO", layout="wide")
st.title("🏠 Ипотечный калькулятор с досрочками и ремонтом")
st.markdown("Сравните несколько вариантов ипотеки с разными ставками, досрочными погашениями и учётом будущего ремонта.")

# Инициализация списка вариантов в сессии
if 'options' not in st.session_state:
    st.session_state.options = []

# --- Боковая панель: Добавление варианта ---
with st.sidebar:
    st.header("➕ Новый вариант")
    with st.form("new_option"):
        name = st.text_input("Название варианта", value="Вариант 1")
        col1, col2 = st.columns(2)
        with col1:
            property_price = st.number_input("Стоимость жилья, ₽", value=6_000_000, step=100_000, format="%d")
            down_payment = st.number_input("Первоначальный взнос, ₽", value=1_500_000, step=100_000, format="%d")
        with col2:
            years = st.number_input("Срок кредита, лет", value=20, min_value=1, max_value=50)
            pay_type = st.selectbox("Тип платежа", ["Аннуитетный", "Дифференцированный"])
        total_loan = property_price - down_payment
        if total_loan <= 0:
            st.error("Взнос должен быть меньше стоимости жилья")
            submitted = st.form_submit_button("Добавить вариант", disabled=True)
        else:
            st.success(f"Сумма кредита: {format_money(total_loan)}")
            # Линии кредита
            st.subheader("Кредитные линии")
            lines_data = st.data_editor(
                pd.DataFrame([
                    {"Название": "Льготная", "Сумма": min(3_000_000, total_loan), "Ставка %": 6.0},
                    {"Название": "Рыночная", "Сумма": max(0, total_loan - 3_000_000), "Ставка %": 10.5}
                ]),
                num_rows="dynamic",
                key="lines_editor"
            )
            # Проверка сумм
            sum_lines = lines_data["Сумма"].sum()
            if abs(sum_lines - total_loan) > 1.0:
                st.warning(f"Сумма линий ({format_money(sum_lines)}) ≠ сумме кредита ({format_money(total_loan)})")
            
            # Досрочные погашения
            st.subheader("Досрочные погашения")
            early_data = st.data_editor(
                pd.DataFrame(columns=["Месяц", "Сумма"]),
                num_rows="dynamic",
                key="early_editor"
            )
            # Ремонт
            st.subheader("Ремонт")
            add_renov = st.checkbox("Учесть ремонт", value=False)
            renov_start = st.number_input("Начало через (лет)", value=3, step=1, disabled=not add_renov)
            renov_dur = st.number_input("Длительность (мес.)", value=15, step=1, disabled=not add_renov)
            renov_cost = st.number_input("Стоимость ремонта, ₽", value=750_000, step=10_000, disabled=not add_renov)

            submitted = st.form_submit_button("Добавить вариант")

        if submitted and total_loan > 0:
            # Формируем транши
            tranches = []
            for _, row in lines_data.iterrows():
                if row["Сумма"] > 0:
                    tranches.append(Tranche(row["Сумма"], row["Ставка %"]))
            # Ранние платежи
            early_list = [EarlyPayment(int(row["Месяц"]), row["Сумма"]) for _, row in early_data.iterrows() if row["Месяц"]>0]
            # Параметры ремонта
            ren_start_yr = renov_start if add_renov else None
            ren_dur_val = renov_dur if add_renov else None
            ren_cost_val = renov_cost if add_renov else None
            
            opt = MortgageOption(
                name=name,
                tranches=tranches,
                years=years,
                pay_type='annuity' if pay_type == "Аннуитетный" else 'diff',
                early_payments=early_list,
                renovation_start_year=ren_start_yr,
                renovation_duration=ren_dur_val,
                renovation_total_cost=ren_cost_val
            )
            st.session_state.options.append(opt)
            st.rerun()

# --- Основная область: отображение вариантов и сравнение ---
if st.session_state.options:
    st.header("📊 Ваши варианты")
    tabs = st.tabs([f"{opt.name}" for opt in st.session_state.options] + ["Сравнение всех"])
    
    for i, opt in enumerate(st.session_state.options):
        with tabs[i]:
            res = opt.compute_schedule()
            ren = opt.renovation_info(res)
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Ежемесячный платёж (ипотека)", format_money(res['first']))
                if ren:
                    st.metric("Ремонт в месяц", format_money(ren['monthly']))
                    st.metric("Пиковая нагрузка", format_money(ren['peak']))
            with col2:
                st.metric("Общая выплата", format_money(res['total_paid']))
                st.metric("Переплата", f"{res['overpayment']:,.2f} ₽ ({res['overpayment']/opt.total_principal()*100:.1f}%)")
            with col3:
                st.metric("Фактический срок", f"{res['actual_months']} мес. ({res['actual_months']//12} лет {res['actual_months']%12} мес.)")
            
            # График платежей во времени
            st.subheader("График ежемесячных расходов")
            months = list(range(1, len(res['payments'])+1))
            mortgage_payments = res['payments']
            renovation_line = []
            for m in months:
                if ren and ren['start'] <= m <= ren['end']:
                    renovation_line.append(ren['monthly'])
                else:
                    renovation_line.append(0)
            total_line = [m + r for m, r in zip(mortgage_payments, renovation_line)]
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=months, y=mortgage_payments, name='Ипотека', fill='tozeroy', line=dict(color='blue')))
            if any(renovation_line):
                fig.add_trace(go.Scatter(x=months, y=renovation_line, name='Ремонт', fill='tozeroy', line=dict(color='orange')))
                fig.add_trace(go.Scatter(x=months, y=total_line, name='Всего', line=dict(color='red', dash='dot')))
            fig.update_layout(title="Платежи по месяцам", xaxis_title="Месяц", yaxis_title="Сумма, ₽")
            st.plotly_chart(fig, use_container_width=True)
            
            # Круговая диаграмма переплаты по линиям
            st.subheader("Структура переплаты")
            # Восстановим проценты по линиям можно из симуляции? Упростим - покажем общую переплату
            overpayment_data = []
            for t in opt.tranches:
                # примерная оценка: доля переплаты пропорционально начальной сумме * ставке
                weight = t.amount * t.rate
                overpayment_data.append(weight)
            total_weight = sum(overpayment_data)
            if total_weight > 0:
                labels = [f"Линия {i+1}: {t.rate}%" for i, t in enumerate(opt.tranches)]
                values = [w / total_weight * res['overpayment'] for w in overpayment_data]
                fig_pie = px.pie(names=labels, values=values, title="Распределение переплаты по ставкам")
                st.plotly_chart(fig_pie, use_container_width=True)

    # Вкладка сравнения
    with tabs[-1]:
        st.header("Сравнительная таблица")
        comparison = []
        for opt in st.session_state.options:
            res = opt.compute_schedule()
            ren = opt.renovation_info(res)
            comparison.append({
                "Название": opt.name,
                "Тип": "Анн." if opt.pay_type == 'annuity' else "Диф.",
                "Платёж (первый/последний)": f"{format_money(res['first'])} / {format_money(res['last'])}",
                "Факт. срок": f"{res['actual_months']} мес.",
                "Общая выплата": format_money(res['total_paid']),
                "Переплата": f"{format_money(res['overpayment'])} ({res['overpayment']/opt.total_principal()*100:.1f}%)",
                "Ремонт/мес": format_money(ren['monthly']) if ren else "—",
                "Пик нагрузки": format_money(ren['peak']) if ren else format_money(res['max'])
            })
        st.dataframe(pd.DataFrame(comparison), use_container_width=True)
        
        # Гистограмма сравнения
        fig_comp = go.Figure()
        for opt in st.session_state.options:
            res = opt.compute_schedule()
            ren = opt.renovation_info(res)
            peak = ren['peak'] if ren else res['max']
            fig_comp.add_trace(go.Bar(name=opt.name, x=['Переплата', 'Пик нагрузки'], 
                                      y=[res['overpayment'], peak], text=[format_money(res['overpayment']), format_money(peak)]))
        fig_comp.update_layout(barmode='group', title="Сравнение ключевых показателей")
        st.plotly_chart(fig_comp, use_container_width=True)

else:
    st.info("Добавьте хотя бы один вариант через боковую панель слева.")