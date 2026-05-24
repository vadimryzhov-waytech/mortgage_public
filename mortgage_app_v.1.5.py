        # График 2: Годовые расходы по вариантам (линии с маркерами + линии необходимого дохода)
        st.subheader("📈 Годовые расходы по вариантам")
        fig_yearly = go.Figure()
        max_year_total = 0
        for opt in visible_opts:
            res = opt.compute_schedule()
            actual_months = res['actual_months']
            payments = res['payments']
            renov_payments = res['renovation_payments'] if 'renovation_payments' in res else [0]*actual_months

            years_list = []
            totals_per_year = []
            for y in range(1, (actual_months // 12) + 2):
                start_idx = (y-1)*12
                end_idx = min(y*12, actual_months)
                if start_idx >= actual_months:
                    break
                mortgage_year = sum(payments[start_idx:end_idx])
                renov_year = sum(renov_payments[start_idx:end_idx])
                total_year = mortgage_year + renov_year
                years_list.append(y)
                totals_per_year.append(total_year)
                max_year_total = max(max_year_total, total_year)

            fig_yearly.add_trace(go.Scatter(
                x=years_list, y=totals_per_year,
                mode='lines+markers',
                name=f"{opt.name}",
                line=dict(width=2),
                marker=dict(size=6)
            ))

            total_cost_all = res['total_paid'] + (opt.renovation_total_cost if opt.renovation_total_cost else 0)
            avg_all = total_cost_all / actual_months if actual_months > 0 else 0
            req_inc_monthly = avg_all + 250_000
            annual_req = req_inc_monthly * 12
            # Аннотация с годовой и месячной суммой
            annotation_text = f"{opt.name}: {format_money(annual_req)}/год ({format_money(req_inc_monthly)}/мес)"
            fig_yearly.add_hline(
                y=annual_req,
                line_dash="dash",
                line_color="gray",
                annotation_text=annotation_text,
                annotation_position="top right"
            )
            max_year_total = max(max_year_total, annual_req)
        fig_yearly.update_layout(
            xaxis_title="Год",
            yaxis=dict(range=[0, max_year_total * 1.1], title="Общие расходы за год, ₽"),
            template='plotly_white',
            hovermode='x unified'
        )
        st.plotly_chart(fig_yearly, use_container_width=True)