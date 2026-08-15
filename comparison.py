import altair as alt
import pandas as pd
import streamlit as st

from service_life import INDEX_COLUMN, group_project_materials, rebuild_draft, sf


# ============================================================================
# 1. MATERIAL / MIX COMPARISON
# ============================================================================
def render_mix_comparison(db, user_mixes, factors_df, all_available_mixes,
                          calc_mix_carbon, safe_float, generate_pdf_report, has_fpdf):
    st.markdown("#### Compare Materials & Mixes")
    st.info("Select multiple materials or custom mixes below to analyse their "
            "sustainability metrics side-by-side.")

    selected_for_comp = st.multiselect("Select Mixes to Compare:", all_available_mixes,
                                       key="compare_multiselect")
    if not selected_for_comp:
        return

    comp_data = []
    for mix_name in selected_for_comp:
        props = calc_mix_carbon(mix_name, db, user_mixes, factors_df)
        mass = props["Mass (kg/m3)"]
        gwp = props["Factor_GWP (kgCO2e/kg)"] * mass
        comp_data.append({
            "Material": mix_name,
            "Total Mass (kg/m³)": mass,
            "GWP100 Factor (kgCO2e/kg)": props["Factor_GWP (kgCO2e/kg)"],
            "Total GWP100 (kgCO2e/m³)": gwp,
        })
    comp_df = pd.DataFrame(comp_data)

    if len(comp_data) <= 1:
        st.error("Please select at least one more material from the dropdown above to "
                 "generate the side-by-side comparison report and visual charts.")
        st.dataframe(comp_df.set_index("Material").style.format({
            "Total Mass (kg/m³)": "{:,.2f}",
            "GWP100 Factor (kgCO2e/kg)": "{:,.3f}",
            "Total GWP100 (kgCO2e/m³)": "{:,.2f}"}), use_container_width=True)
        return

    st.markdown("---")
    sorted_df = comp_df.sort_values("Total GWP100 (kgCO2e/m³)")
    best, worst = sorted_df.iloc[0], sorted_df.iloc[-1]
    if worst["Total GWP100 (kgCO2e/m³)"] > 0:
        savings_pct = ((worst["Total GWP100 (kgCO2e/m³)"] - best["Total GWP100 (kgCO2e/m³)"])
                       / worst["Total GWP100 (kgCO2e/m³)"]) * 100
    else:
        savings_pct = 0

    st.markdown(f"""
    <div style="background-color: #E8F8F5; padding: 20px; border-radius: 8px;
                border-left: 6px solid #1ABC9C; margin-bottom: 20px;">
        <h4 style="margin-top: 0; color: #2C3E50;">Executive Summary and Technical Insight</h4>
        <p style="font-size: 16px; color: #34495E; line-height: 1.6;">
        This comparative analysis evaluates the <strong>Embodied Carbon Intensity (ECI)</strong>
        across your selected structural materials. Based on the dataset,
        <strong>{best['Material']}</strong> demonstrates optimal environmental performance,
        yielding a Global Warming Potential (GWP100) of
        <strong>{best['Total GWP100 (kgCO2e/m³)']:,.2f} kgCO2e/m³</strong> at a density of
        <strong>{best['Total Mass (kg/m³)']:,.2f} kg/m³</strong>.
        <br><br>
        Choosing the optimal material (<strong>{best['Material']}</strong>) instead of the
        highest-impact option (<strong>{worst['Material']}</strong>) results in a
        <strong>{savings_pct:.1f}% reduction</strong> in environmental impact per cubic metre.
        For large-scale infrastructure applications, this material substitution represents a
        highly effective decarbonisation strategy.
        </p>
    </div>""", unsafe_allow_html=True)

    st.markdown("##### Visual Analytics")
    tab_bar, tab_scatter, tab_matrix = st.tabs(
        ["GWP100 Leaderboard", "Density vs. Carbon Trade-off", "Ingredient Matrix"])

    with tab_bar:
        best_val = float(best["Total GWP100 (kgCO2e/m³)"])
        base_chart = alt.Chart(comp_df).encode(
            x=alt.X("Total GWP100 (kgCO2e/m³):Q",
                    title="Global Warming Potential (kgCO2e/m³)",
                    scale=alt.Scale(domain=[0, comp_df["Total GWP100 (kgCO2e/m³)"].max() * 1.15])),
            y=alt.Y("Material:N", sort="-x", title=""))
        bars = base_chart.mark_bar(cornerRadiusEnd=4, height=40).encode(
            color=alt.condition(alt.datum["Total GWP100 (kgCO2e/m³)"] == best_val,
                                alt.value("#27ae60"), alt.value("#95a5a6")),
            tooltip=["Material", "Total Mass (kg/m³)", "Total GWP100 (kgCO2e/m³)"])
        text = base_chart.mark_text(align="left", baseline="middle", dx=5,
                                    fontWeight="bold").encode(
            text=alt.Text("Total GWP100 (kgCO2e/m³):Q", format=",.2f"))
        st.altair_chart((bars + text).properties(height=alt.Step(60)), use_container_width=True)

    with tab_scatter:
        scatter = alt.Chart(comp_df).mark_circle(size=200).encode(
            x=alt.X("Total Mass (kg/m³):Q", title="Density (kg/m³)",
                    scale=alt.Scale(zero=False, padding=20)),
            y=alt.Y("Total GWP100 (kgCO2e/m³):Q", title="Total GWP100 (kgCO2e/m³)",
                    scale=alt.Scale(zero=False, padding=20)),
            color=alt.Color("Material:N", legend=alt.Legend(title="Material")),
            tooltip=["Material", "Total Mass (kg/m³)", "Total GWP100 (kgCO2e/m³)"]
        ).properties(height=350)
        st.altair_chart(scatter, use_container_width=True)

    with tab_matrix:
        st.markdown("**Side-by-Side Ingredient Comparison (kg per m³)**")
        matrix_data = []
        for mix_name in selected_for_comp:
            found = False
            if mix_name.startswith("Custom: "):
                mix_n = mix_name.replace("Custom: ", "")
                match_mix = next((m for m in user_mixes if m["mix_name"] == mix_n), None)
                if match_mix:
                    for c, val in (match_mix.get("components") or {}).items():
                        if safe_float(val) > 0:
                            matrix_data.append({"Mix": mix_name, "Ingredient": c,
                                                "Mass (kg)": safe_float(val)})
                            found = True
                    for adhoc in (match_mix.get("adhoc_materials") or []):
                        if safe_float(adhoc.get("Quantity")) > 0:
                            matrix_data.append({"Mix": mix_name,
                                                "Ingredient": adhoc["Material Name"],
                                                "Mass (kg)": safe_float(adhoc.get("Quantity"))})
                            found = True
            else:
                mdf = (db["mixes"][db["mixes"]["Mix_Key"] == mix_name]
                       if not db["mixes"].empty and "Mix_Key" in db["mixes"].columns
                       else pd.DataFrame())
                if not mdf.empty:
                    mix_row = mdf.iloc[0]
                    for comp in factors_df.index:
                        if comp in mix_row and pd.notna(mix_row[comp]) \
                                and safe_float(mix_row[comp]) > 0:
                            matrix_data.append({"Mix": mix_name, "Ingredient": comp,
                                                "Mass (kg)": safe_float(mix_row[comp])})
                            found = True
            if not found:
                props = calc_mix_carbon(mix_name, db, user_mixes, factors_df)
                matrix_data.append({"Mix": mix_name,
                                    "Ingredient": f"{mix_name} (Base Material)",
                                    "Mass (kg)": props["Mass (kg/m3)"]})
        if matrix_data:
            pivot_df = pd.DataFrame(matrix_data).pivot_table(
                index="Ingredient", columns="Mix", values="Mass (kg)", fill_value=0)
            st.dataframe(pivot_df.style.format("{:,.2f}"), use_container_width=True)

    st.markdown("##### Detailed Metric Breakdown & Data Export")

    def highlight_best(s):
        is_min = s == s.min()
        return ["background-color: #d4edda; color: #155724; font-weight: bold" if v else ""
                for v in is_min]

    styled = comp_df.set_index("Material").style.apply(highlight_best).format({
        "Total Mass (kg/m³)": "{:,.2f}",
        "GWP100 Factor (kgCO2e/kg)": "{:,.3f}",
        "Total GWP100 (kgCO2e/m³)": "{:,.2f}"})
    st.table(styled)

    st.markdown("<br>", unsafe_allow_html=True)
    col_csv, col_pdf, _ = st.columns([1, 1, 1.5])
    col_csv.download_button("📄 Download Data (CSV)",
                            data=comp_df.to_csv(index=False).encode("utf-8"),
                            file_name="material_comparison.csv", mime="text/csv",
                            use_container_width=True)
    if has_fpdf:
        pdf_bytes = generate_pdf_report(comp_df, best, worst, savings_pct)
        if pdf_bytes:
            col_pdf.download_button("📊 Download PDF Report", data=pdf_bytes,
                                    file_name="sustainability_report.pdf",
                                    mime="application/pdf", use_container_width=True)


# ============================================================================
# 2. PROJECT COMPARISON
# ============================================================================
def render_project_comparison(supabase, db, user_mixes, factors_df,
                              calc_mix_carbon, calculate_project_data):
    st.markdown("#### Compare Projects")
    st.info("Select two or more saved projects to compare their embodied carbon, material "
            "split, and both carbon efficiency values where the service life has been assessed.")

    try:
        res = supabase.table("saved_projects").select("*") \
            .eq("user_id", st.session_state.user_id).execute()
        projects = res.data or []
    except Exception:
        projects = []

    if not projects:
        st.info("No saved projects on your account yet.")
        return

    names = list(dict.fromkeys([p["project_name"] for p in projects if p.get("project_name")]))
    picked = st.multiselect("Select projects to compare:", names, key="proj_compare_pick")
    if len(picked) < 2:
        st.caption("Pick at least two projects.")
        return

    summary_rows, split_rows, csepp_rows = [], [], []
    for name in picked:
        p = next((x for x in projects if x["project_name"] == name), None)
        if not p:
            continue
        df, totals, _ = calculate_project_data(rebuild_draft(p), db, user_mixes, factors_df)
        if df is None:
            continue
        mats = group_project_materials(df, db, user_mixes, factors_df, calc_mix_carbon)
        vol = sf(mats["Volume (m³)"].sum())
        gwp = sf(totals.get("gwp"))
        row = {
            "Project": name,
            "Structure": p.get("structure_type", ""),
            "No. of materials": len(mats),
            "Total Volume (m³)": vol,
            "Total Mass (t)": sf(totals.get("mass")) / 1000.0,
            "Total GWP100 (tCO2e)": gwp / 1000.0,
            "Carbon Intensity (kgCO2e/m³)": (gwp / vol) if vol > 0 else 0.0,
        }
        sl = p.get("service_life_data") or {}
        summ = sl.get("summary") or {}
        if summ:
            row["Exposure"] = sl.get("exposure_class", "")
            row["Governing tsl (yr)"] = sf(summ.get("governing_tsl"))
            row["Sum of material values"] = sf(summ.get("sum_csepp"))
            row["Whole structure value"] = sf(summ.get("structure_csepp"))
            row["Durability"] = "All pass" if summ.get("all_pass") else \
                f"{int(sf(summ.get('n_pass')))}/{int(sf(summ.get('n_materials')))} pass"
            for r in (sl.get("materials") or sl.get("results") or []):
                csepp_rows.append({"Project": name, "Material": r.get("Material"),
                                   "Carbon efficiency index": sf(r.get(INDEX_COLUMN))})
        else:
            row["Exposure"] = "not assessed"
            row["Governing tsl (yr)"] = float("nan")
            row["Sum of material values"] = float("nan")
            row["Whole structure value"] = float("nan")
            row["Durability"] = "-"
        summary_rows.append(row)

        for _, m in mats.iterrows():
            split_rows.append({"Project": name, "Material": m["Material"],
                               "GWP100 (tCO2e)": sf(m["GWP100 (kgCO2e)"]) / 1000.0,
                               "Volume (m³)": sf(m["Volume (m³)"])})

    if not summary_rows:
        st.error("None of the selected projects could be recalculated.")
        return

    sum_df = pd.DataFrame(summary_rows)
    st.markdown("##### Headline comparison")
    st.dataframe(sum_df.set_index("Project").style.format({
        "Total Volume (m³)": "{:,.2f}", "Total Mass (t)": "{:,.2f}",
        "Total GWP100 (tCO2e)": "{:,.3f}", "Carbon Intensity (kgCO2e/m³)": "{:,.2f}",
        "Governing tsl (yr)": "{:,.0f}",
        "Sum of material values": "{:,.2f}", "Whole structure value": "{:,.2f}"}, na_rep="-"),
        use_container_width=True)

    best_row = sum_df.sort_values("Total GWP100 (tCO2e)").iloc[0]
    st.success(f"**Lowest total embodied carbon:** {best_row['Project']} at "
               f"{best_row['Total GWP100 (tCO2e)']:,.3f} tCO2e "
               f"({best_row['Carbon Intensity (kgCO2e/m³)']:,.2f} kgCO2e/m³).")

    valid = sum_df.dropna(subset=["Whole structure value"])
    if not valid.empty:
        top_s = valid.sort_values("Whole structure value", ascending=False).iloc[0]
        top_sum = valid.sort_values("Sum of material values", ascending=False).iloc[0]
        st.success(
            f"**Best carbon efficiency for the whole structure:** "
            f"{top_s['Project']} at {top_s['Whole structure value']:,.2f} megapascal years per tonne CO2e. "
            f"**Highest sum of material values:** {top_sum['Project']} at {top_sum['Sum of material values']:,.2f}. "
            f"The whole structure value is the fair comparison across designs that differ in "
            f"size or in the number of mixes. The sum of the material values grows with the "
            f"number of materials, so use it within a family of similar designs.")
    else:
        st.warning("None of the selected projects has saved service life data yet, so "
                   "cannot be compared. Run the Service Life and CSEPP page for each project "
                   "and press Save.")

    t1, t2, t3, t4 = st.tabs(["Carbon totals", "Material split",
                              "Efficiency by material", "The two efficiency values"])
    with t1:
        chart = alt.Chart(sum_df).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("Total GWP100 (tCO2e):Q", title="Total GWP100 (tonne CO2e)"),
            y=alt.Y("Project:N", sort="-x", title=""),
            color=alt.Color("Project:N", legend=None),
            tooltip=["Project", "Structure", "Total GWP100 (tCO2e)",
                     "Carbon Intensity (kgCO2e/m³)"]).properties(height=alt.Step(45))
        st.altair_chart(chart, use_container_width=True)
    with t2:
        sp = pd.DataFrame(split_rows)
        stacked = alt.Chart(sp).mark_bar().encode(
            x=alt.X("GWP100 (tCO2e):Q", stack="normalize", title="Share of project GWP100"),
            y=alt.Y("Project:N", title=""),
            color=alt.Color("Material:N", legend=alt.Legend(orient="bottom")),
            tooltip=["Project", "Material", "GWP100 (tCO2e)", "Volume (m³)"]
        ).properties(height=alt.Step(45))
        st.altair_chart(stacked, use_container_width=True)
        st.dataframe(sp.pivot_table(index="Material", columns="Project",
                                    values="GWP100 (tCO2e)", fill_value=0)
                     .style.format("{:,.3f}"), use_container_width=True)
    with t3:
        if csepp_rows:
            cd = pd.DataFrame(csepp_rows)
            cd = cd[cd["Carbon efficiency index"] > 0]
            if not cd.empty:
                grouped = alt.Chart(cd).mark_bar().encode(
                    x=alt.X("Carbon efficiency index:Q",
                            title="Carbon efficiency index, megapascal years per tonne CO2e"),
                    y=alt.Y("Material:N", title=""),
                    color=alt.Color("Project:N"), yOffset="Project:N",
                    tooltip=["Project", "Material", "Carbon efficiency index"]).properties(height=alt.Step(30))
                st.altair_chart(grouped, use_container_width=True)
            else:
                st.info("No material passed the durability check in the saved results.")
        else:
            st.info("No carbon efficiency results have been saved for the selected projects.")
    with t4:
        if not valid.empty:
            melt = valid.melt(id_vars="Project", value_vars=["Sum of material values", "Whole structure value"],
                              var_name="Metric", value_name="Value")
            side = alt.Chart(melt).mark_bar().encode(
                x=alt.X("Value:Q", title="Carbon efficiency index, megapascal years per tonne CO2e"),
                y=alt.Y("Project:N", title=""),
                color=alt.Color("Metric:N", legend=alt.Legend(orient="bottom")),
                yOffset="Metric:N",
                tooltip=["Project", "Metric", "Value"]).properties(height=alt.Step(40))
            st.altair_chart(side, use_container_width=True)
            st.caption("Both values shown side by side. They differ in size by construction. The sum "
                       "of the material values adds one term for every material, while the whole "
                       "structure value treats the structure as a single equivalent material.")
        else:
            st.info("No service life data available for the selected projects.")

    st.download_button("📄 Download project comparison (CSV)",
                       data=sum_df.to_csv(index=False).encode("utf-8"),
                       file_name="project_comparison.csv", mime="text/csv")


# ============================================================================
# 3. PAGE ROUTER
# ============================================================================
def render_comparison_page(supabase, db, user_mixes, factors_df, all_available_mixes,
                           calc_mix_carbon, calculate_project_data, safe_float,
                           generate_pdf_report, has_fpdf):
    view = st.radio("Select comparison type:",
                    ["Material / Mix Comparison", "Project Comparison"],
                    horizontal=True, label_visibility="collapsed", key="cmp_view")
    st.markdown("---")
    if view == "Material / Mix Comparison":
        render_mix_comparison(db, user_mixes, factors_df, all_available_mixes,
                              calc_mix_carbon, safe_float, generate_pdf_report, has_fpdf)
    else:
        render_project_comparison(supabase, db, user_mixes, factors_df,
                                  calc_mix_carbon, calculate_project_data)
