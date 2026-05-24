import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import math

# ------------------- Расчётные функции -------------------
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
                 renovation_start_year=None, renovation_duration=None, renovation_total_cost=None,
                 visible=True):
        self.name = name
        self.tranches = tranches
        self.years = years
        self.months = years * 12
        self.pay_type = pay_type
        self.early_payments = early_payments or []
        self.renovation_start_month = (renovation_start_year * 12 + 1) if renovation_start_year is not None else None
        self.renovation_duration = renovation_duration
        self.renovation_total_cost = renovation_total_cost
        self.visible = visible

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

    def _apply_early(self, lines, amount):
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

        payments_by_tranche = [[] for _ in lines]
        total_payments = []
        renovation_payments = []
        month = 1
        total_paid = 0.0

        while any(t.remaining > 1e-9 for t in lines):
            for ep in early_sorted:
                if ep.month == month:
                    self._apply_early(lines, ep.amount)

            monthly_tranche_payments = []
            monthly_sum = 0.0
            for idx, t in enumerate(lines):
                if t.remaining > 1e-9:
                    mr = t.rate / 100 / 12
                    interest = t.remaining * mr
                    if self.pay_type == 'annuity':
                        max_pm = t.remaining + interest
                        actual = min(t.monthly_payment, max_pm)
                        if actual >= interest:
                            principal_paid = actual - interest
                            t.remaining -= principal_paid
                        else:
                            t.remaining = max(0, t.remaining)
                    else:
                        principal = min(t.base_principal, t.remaining)
                        actual = principal + interest
                        t.remaining -= principal
                    monthly_tranche_payments.append(actual)
                    monthly_sum += actual
                else:
                    monthly_tranche_payments.append(0.0)
            payments_by_tranche.append(monthly_tranche_payments)
            total_payments.append(monthly_sum)
            total_paid += monthly_sum
            month += 1
            if month > 1200:
                break

        if self.renovation_start_month is not None:
            renov_monthly = self.renovation_total_cost / self.renovation_duration
            for m in range(1, len(total_payments)+1):
                if self.renovation_start_month <= m <= self.renovation_start_month + self.renovation_duration - 1:
                    renovation_payments.append(renov_monthly)
                else:
                    renovation_payments.append(0.0)

        return {
            'payments': total_payments,
            'payments_by_tranche': payments_by_tranche,
            'renovation_payments': renovation_payments,
            'total_paid': total_paid,
            'overpayment': total_paid - sum(t.amount for t in self.tranches),
            'actual_months': len(total_payments),
            'first': total_payments[0] if total_payments else 0,
            'last': total_payments[-1] if total_payments else 0,
            'min': min(total_payments) if total_payments else 0,
            'max': max(total_payments) if total_payments else 0,
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

def format_money(value):
    return f"{value:,.0f} ₽"

# ------------------- Интерфейс Streamlit -------------------
st.set_page_config(page_title="Ипотечный калькулятор PRO", layout="wide")
st.title("🏠 Ипотечный калькулятор с досрочками и ремонтом")
st.markdown("Настройте параметры ипотеки, добавьте несколько вариантов и сравните их наглядно.")

if 'options' not in st.session_state:
    st.session_state.options = []

# Боковая панель добавления варианта (без формы, динамическое обновление)
with st.sidebar:
    st.header("➕ Новый вариант")
    name = st.text_input("Название варианта", value="Вариант 1")
    col1, col2 = st.columns(2)
    with col1:
        property_price = st.number_input("Стоимость жилья, ₽", value=30_000_000, step=100_000, format="%d")
        down_payment = st.number_input("Первоначальный взнос, ₽", value=6_000_000, step=100_000, format="%d")
    with col2:
        years = st.slider("Срок кредита, лет", 1, 30, 20)
        pay_type = st.radio("Тип платежа", ["Аннуитетный", "Дифференцированный"], horizontal=True)
    total_loan = property_price - down_payment
    if total_loan <= 0:
        st.error("Взнос должен быть меньше стоимости жилья")
    else:
        st.success(f"Сумма кредита: {format_money(total_loan)}")
        st.subheader("Кредитные линии")
        lines_count = st.number_input("Количество линий", min_value=1, max_value=5, value=2, key="lines_count")
        # Сбор введённых сумм для динамического остатка
        line_amounts = []
        remaining = float(total_loan)
        for i in range(int(lines_count)):
            cols = st.columns([2,1,1])
            with cols[0]:
                if i == 0:
                    default_amount = float(min(3_000_000, remaining))
                else:
                    default_amount = float(max(0.0, min(remaining, total_loan - 3_000_000)))
                amount = st.number_input(
                    f"Сумма Линия {i+1}",
                    min_value=0.0,
                    value=default_amount,
                    step=100_000.0,
                    key=f"amount_{i}"
                )
            with cols[1]:
                default_rate = 6.0 if i == 0 else 18.0
                rate = st.number_input(
                    f"Ставка % Линия {i+1}",
                    min_value=0.0,
                    value=default_rate,
                    step=0.1,
                    key=f"rate_{i}"
                )
            with cols[2]:
                # Вместо статичного остатка показываем накопленный остаток
                pass
            line_amounts.append(amount)
            remaining = float(total_loan) - sum(line_amounts)
        # Динамический остаток – показываем после цикла
        st.caption(f"**Остаток к распределению: {format_money(remaining)}**")
        if remaining < -0.01:
            st.warning("Сумма линий превышает сумму кредита!")
        # --- Досрочные погашения ---
        st.subheader("Досрочные погашения")
        add_early = st.checkbox("Добавить досрочки")
        early_list = []
        if add_early:
            early_count = st.number_input("Количество досрочек", min_value=1, max_value=10, value=1, key="early_count")
            for j in range(int(early_count)):
                c1, c2 = st.columns(2)
                with c1:
                    month = st.number_input(f"Месяц #{j+1}", min_value=1, value=12*(j+1), step=1, key=f"em_{j}")
                with c2:
                    amt = st.number_input(f"Сумма #{j+1}", min_value=0.0, value=500_000.0, step=100_000.0, key=f"ea_{j}")
                early_list.append(EarlyPayment(int(month), amt))

        # --- Ремонт ---
        st.subheader("Ремонт")
        add_renov = st.checkbox("Учесть ремонт", value=True)
        if add_renov:
            c1, c2, c3 = st.columns(3)
            with c1:
                start_yr = st.number_input("Начало через, лет", min_value=0, value=3, step=1)
            with c2:
                dur = st.number_input("Длительность, мес.", min_value=1, value=18, step=1)
            with c3:
                cost = st.number_input("Стоимость, ₽", min_value=0.0, value=10_000_000.0, step=100_000.0)
        else:
            start_yr = dur = cost = None

        # Кнопка добавления
        if st.button("Добавить вариант"):
            # Проверим остаток
            total_entered = sum(line_amounts)
            if abs(total_entered - total_loan) > 100:  # допуск
                st.error("Сумма кредитных линий должна равняться сумме кредита!")
            else:
                final_tranches = []
                for i in range(int(lines_count)):
                    amt = line_amounts[i]
                    rate = st.session_state.get(f"rate_{i}", 0.0)
                    if amt > 0:
                        final_tranches.append(Tranche(float(amt), float(rate)))
                opt = MortgageOption(
                    name=name,
                    tranches=final_tranches,
                    years=years,
                    pay_type='annuity' if pay_type == "Аннуитетный" else 'diff',
                    early_payments=early_list,
                    renovation_start_year=start_yr,
                    renovation_duration=dur,
                    renovation_total_cost=cost,
                    visible=True
                )
                st.session_state.options.append(opt)
                st.rerun()

    # Управление видимостью вариантов
    if st.session_state.options:
        st.divider()
        st.subheader("🎯 Показать / скрыть варианты")
        for i, opt in enumerate(st.session_state.options):
            key = f"vis_{i}"
            new_val = st.checkbox(f"{opt.name}", value=opt.visible, key=key)
            if new_val != opt.visible:
                st.session_state.options[i].visible = new_val
                st.rerun()

# ------------------- Основная область: отображение -------------------
visible_opts = [o for o in st.session_state.options if o.visible]

if visible_opts:
    tab_names = [opt.name for opt in visible_opts] + ["📊 Сравнение всех"]
    tabs = st.tabs(tab_names)

    for i, opt in enumerate(visible_opts):
        with tabs[i]:
            res = opt.compute_schedule()
            ren = opt.renovation_info(res)
            first_month_payments = res['payments_by_tranche'][0] if res['payments_by_tranche'] else []

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Ежемесячный платёж (ипотека)", format_money(res['first']))
                if ren:
                    st.metric("Ремонт в месяц", format_money(ren['monthly']))
                    st.metric("Пиковая нагрузка", format_money(ren['peak']))
            with col2:
                st.metric("Общая выплата", format_money(res['total_paid']))
                over_pct = res['overpayment'] / opt.total_principal() * 100
                st.metric("Переплата", f"{format_money(res['overpayment'])} ({over_pct:.1f}%)")
            with col3:
                actual_y = res['actual_months'] // 12
                actual_m = res['actual_months'] % 12
                st.metric("Фактический срок", f"{res['actual_months']} мес. ({actual_y} г. {actual_m} мес.)")

            # ---- Общая сумма платежа и разбивка ----
            total_first_month = res['first'] + (ren['monthly'] if ren else 0)
            st.subheader("💳 Ежемесячный платёж (первый месяц)")
            st.markdown(f"### **Общая сумма: {format_money(total_first_month)}**")
            st.markdown("**В том числе:**")
            lines_text = ""
            for idx, t in enumerate(opt.tranches):
                line_name = f"Линия {idx+1} ({t.rate}%)"
                if idx < len(first_month_payments):
                    payment = first_month_payments[idx]
                    lines_text += f"- {line_name}: {format_money(payment)}\n"
                else:
                    lines_text += f"- {line_name}: 0 ₽\n"
            if ren:
                lines_text += f"- Ремонт: {format_money(ren['monthly'])}\n"
            st.markdown(lines_text)

            # График №1: общие платежи
            st.subheader("📈 График ежемесячных расходов")
            months = list(range(1, len(res['payments'])+1))
            mortgage = res['payments']
            renovation_line = res.get('renovation_payments', [0]*len(months))
            total_line = [m + r for m, r in zip(mortgage, renovation_line)]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=months, y=mortgage,
                mode='lines+markers',
                name='Ипотека (все линии)',
                line=dict(color='#1f77b4', width=2),
                marker=dict(size=3)
            ))
            if any(renovation_line):
                fig.add_trace(go.Scatter(
                    x=months, y=renovation_line,
                    mode='lines+markers',
                    name='Ремонт',
                    line=dict(color='#ff7f0e', width=2),
                    marker=dict(size=3)
                ))
                fig.add_trace(go.Scatter(
                    x=months, y=total_line,
                    mode='lines+markers',
                    name='Всего',
                    line=dict(color='red', dash='dot', width=2),
                    marker=dict(size=3)
                ))
            fig.update_layout(
                xaxis_title="Месяц",
                yaxis_title="Сумма, ₽",
                hovermode='x unified',
                template='plotly_white'
            )
            st.plotly_chart(fig, use_container_width=True)

            # График №2: структура
            st.subheader("🍰 Структура ежемесячного платежа")
            num_tranches = len(opt.tranches)
            stacked_data = {f"Линия {j+1} ({t.rate}%)": [] for j, t in enumerate(opt.tranches)}
            if ren:
                stacked_data["Ремонт"] = []

            for m_idx in range(len(months)):
                tranche_pmts = res['payments_by_tranche'][m_idx] if m_idx < len(res['payments_by_tranche']) else [0]*num_tranches
                for j in range(num_tranches):
                    key = f"Линия {j+1} ({opt.tranches[j].rate}%)"
                    stacked_data[key].append(tranche_pmts[j] if j < len(tranche_pmts) else 0)
                if ren:
                    stacked_data["Ремонт"].append(renovation_line[m_idx] if m_idx < len(renovation_line) else 0)

            fig2 = go.Figure()
            for name, values in stacked_data.items():
                fig2.add_trace(go.Scatter(
                    x=months,
                    y=values,
                    mode='lines',
                    stackgroup='one',
                    name=name,
                    line=dict(width=0.5),
                    hovertemplate='%{y:,.0f} ₽<extra>%{fullData.name}</extra>'
                ))
            fig2.update_layout(
                xaxis_title="Месяц",
                yaxis_title="Сумма, ₽",
                hovermode='x unified',
                template='plotly_white',
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig2, use_container_width=True)

    # Вкладка сравнения
    with tabs[-1]:
        st.header("📊 Сравнение всех вариантов")
        table_data = []
        for opt in visible_opts:
            res = opt.compute_schedule()
            ren = opt.renovation_info(res)
            table_data.append({
                "Название": opt.name,
                "Тип": "Анн." if opt.pay_type == 'annuity' else "Диф.",
                "Платёж (первый/последний)": f"{format_money(res['first'])} / {format_money(res['last'])}",
                "Срок факт.": f"{res['actual_months']} мес.",
                "Общая выплата": format_money(res['total_paid']),
                "Переплата": f"{format_money(res['overpayment'])} ({res['overpayment']/opt.total_principal()*100:.1f}%)",
                "Ремонт/мес": format_money(ren['monthly']) if ren else "—",
                "Пик нагрузки": format_money(ren['peak']) if ren else format_money(res['max'])
            })
        st.dataframe(pd.DataFrame(table_data), use_container_width=True)

        if len(visible_opts) > 0:
            fig_bar = go.Figure()
            for opt in visible_opts:
                res = opt.compute_schedule()
                ren = opt.renovation_info(res)
                peak = ren['peak'] if ren else res['max']
                fig_bar.add_trace(go.Bar(
                    name=opt.name,
                    x=['Переплата', 'Пик нагрузки'],
                    y=[res['overpayment'], peak],
                    text=[format_money(res['overpayment']), format_money(peak)],
                ))
            fig_bar.update_layout(barmode='group', template='plotly_white')
            st.plotly_chart(fig_bar, use_container_width=True)
else:
    st.info("👈 Добавьте первый вариант ипотеки через боковую панель слева и включите его видимость.")