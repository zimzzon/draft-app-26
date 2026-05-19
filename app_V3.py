import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import numpy as np

# --- KONFIGURATION ---
CSV_PFAD = "26_draft_projections.csv"
POS_COLORS = {
    'QB': '#e63946', 'RB': '#2a9d8f', 'WR': '#457b9d', 'TE': '#f4a261', 
    'K': '#a8dadc', 'DST': '#1d3557'
}

QUELLEN_SPALTEN = ['CBS', 'ESPN', 'FantasyPros', 'FantasySharks', 'RTSports'] 
ADP_SPALTEN = ['adp_average', 'adp_yahoo', 'adp_espn', 'adp_nfl']

st.set_page_config(page_title="FF Draft Assistant 26", layout="wide", initial_sidebar_state="expanded")

# --- 1. DATEN LADEN ---
@st.cache_data
def load_raw_data():
    try:
        df = pd.read_csv(CSV_PFAD)
        df['pos'] = df['pos'].astype('category')
        if 'team' in df.columns:
            df['team'] = df['team'].astype('category')
        return df
    except FileNotFoundError:
        st.error(f"Fehler: CSV-Datei '{CSV_PFAD}' nicht gefunden.")
        st.stop()

raw_df = load_raw_data()

# Session State Initialisierung
if 'drafted_names' not in st.session_state:
    st.session_state.drafted_names = []
    st.session_state.history = []
    st.session_state.queue = [] 

# --- 2. SIDEBAR: EINSTELLUNGEN & GEWICHTUNG ---
with st.sidebar:
    st.header("🏈 Roster & Liga Settings")
    TEAMS_IN_LEAGUE = st.number_input("Teams in der Liga", min_value=8, max_value=16, value=12)
    qb_spots = st.number_input("Starting QBs", 1, 3, 1)
    rb_spots = st.number_input("Starting RBs", 1, 4, 2)
    wr_spots = st.number_input("Starting WRs", 1, 4, 2)
    flex_spots = st.number_input("FLEX (RB/WR/TE)", 0, 4, 1)
    te_spots = st.number_input("Starting TEs", 1, 3, 1)
    bench_spots = st.number_input("Bench Spots", 0, 15, 6)
    
    BASELINES_STARTER = {
        'QB': int(TEAMS_IN_LEAGUE * qb_spots) + 1 if qb_spots == 1 else int(TEAMS_IN_LEAGUE * qb_spots),
        'RB': int(TEAMS_IN_LEAGUE * (rb_spots + flex_spots * 0.45)),
        'WR': int(TEAMS_IN_LEAGUE * (wr_spots + flex_spots * 0.45)),
        'TE': int(TEAMS_IN_LEAGUE * te_spots) + 1 if te_spots == 1 else int(TEAMS_IN_LEAGUE * te_spots),
        'K': int(TEAMS_IN_LEAGUE * 1),
        'DST': int(TEAMS_IN_LEAGUE * 1)
    }

    BASELINES_WAIVER = {
        'QB': int(TEAMS_IN_LEAGUE * qb_spots * 1.5),
        'RB': int(TEAMS_IN_LEAGUE * (rb_spots + flex_spots * 0.45) * 2),
        'WR': int(TEAMS_IN_LEAGUE * (wr_spots + flex_spots * 0.45) * 2),
        'TE': int(TEAMS_IN_LEAGUE * te_spots * 1.5),
        'K': int(TEAMS_IN_LEAGUE * 1.5),
        'DST': int(TEAMS_IN_LEAGUE * 1.5)
    }

    st.markdown("---")
    
    # === NEU: PROJEKTIONEN & GEWICHTUNG ===
    with st.expander("📊 Projektionen & Gewichtung", expanded=True):
        st.caption("Welche Quellen sollen einfließen und wie stark?")
        selected_sources = []
        source_weights = {}
        
        available_sources = [col for col in QUELLEN_SPALTEN if col in raw_df.columns]
        for src in available_sources:
            col1, col2 = st.columns([1, 2])
            use_src = col1.checkbox(src, value=True)
            if use_src:
                w = col2.slider("Gewicht", 0, 100, 100, key=f"w_{src}", label_visibility="collapsed")
                if w > 0:
                    selected_sources.append(src)
                    source_weights[src] = w
                    
        if not selected_sources:
            st.error("Bitte mindestens eine Quelle mit Gewicht > 0 auswählen!")
            st.stop()

    # === NEU: ADP ANZEIGE ===
    with st.expander("📉 ADP Anzeige", expanded=False):
        st.caption("Welche ADPs sollen in den Tabellen sichtbar sein?")
        selected_adps = []
        available_adps = [col for col in ADP_SPALTEN if col in raw_df.columns]
        for adp_col in available_adps:
            # adp_average standardmäßig an, der Rest aus
            if st.checkbox(adp_col, value=(adp_col == 'adp_average')):
                selected_adps.append(adp_col)

    st.markdown("---")
    with st.expander("⚖️ VONA Gewichtung (Opponent)", expanded=False):
        adp_weight_raw = st.number_input("ADP / Plattform (%)", 0, 100, 75)
        z_weight_raw = st.number_input("Z-Score (%)", 0, 100, 15)
        vor_weight_raw = st.number_input("VOR Waiver (%)", 0, 100, 10)
        total_weight = adp_weight_raw + z_weight_raw + vor_weight_raw
        if total_weight == 0: total_weight = 1
        ADP_W = adp_weight_raw / total_weight
        Z_W = z_weight_raw / total_weight
        VOR_W = vor_weight_raw / total_weight

    st.markdown("---")
    st.header("⚙️ Draft Setup")
    my_team_id = st.number_input("Meine Draft-Position (1-12):", min_value=1, max_value=int(TEAMS_IN_LEAGUE), value=1)
    
    def get_team_for_pick(pick_num):
        round_num = (pick_num - 1) // TEAMS_IN_LEAGUE + 1
        pick_in_round = (pick_num - 1) % TEAMS_IN_LEAGUE + 1
        if round_num % 2 != 0: return pick_in_round
        else: return TEAMS_IN_LEAGUE - pick_in_round + 1

    current_pick_num = len(st.session_state.history) + 1
    current_team_up = get_team_for_pick(current_pick_num)
    
    next_own_pick = current_pick_num
    while get_team_for_pick(next_own_pick) != my_team_id:
        next_own_pick += 1
    
    subsequent_own_pick = next_own_pick + 1
    while get_team_for_pick(subsequent_own_pick) != my_team_id:
        subsequent_own_pick += 1

    picks_until_next = subsequent_own_pick - current_pick_num


# --- 3. DYNAMISCHE DATENAUFBEREITUNG (Punkte & Metriken) ---
working_df = raw_df.copy()

# 3.1 Vektorisierte Berechnung der gewichteten Punkte
w_series = pd.Series(source_weights)
mask = working_df[selected_sources].notna()
w_matrix = mask * w_series
sum_weights = w_matrix.sum(axis=1)
weighted_sum = (working_df[selected_sources].fillna(0) * w_series).sum(axis=1)

working_df['points'] = np.where(sum_weights > 0, weighted_sum / sum_weights, 0)
working_df['sd_pts'] = working_df[selected_sources].std(axis=1).fillna(0)

# VONA-Simulator benötigt ein einheitliches ADP als Referenz (adp_average bevorzugt)
working_df['adp'] = working_df['adp_average'].fillna(999) if 'adp_average' in working_df.columns else 999

def calculate_dynamic_metrics(df):
    df = df.sort_values(by=['pos', 'points'], ascending=[True, False]).reset_index(drop=True)
    df['original_pos_rank'] = df.groupby('pos')['points'].rank(ascending=False, method='first')
    df['Pos Rank'] = df['pos'].astype(str) + "#" + df['original_pos_rank'].astype(int).astype(str)
    
    def get_baseline_pts(pos, baseline_dict):
        rank = baseline_dict.get(pos, 1)
        baseline_row = df[(df['pos'] == pos) & (df['original_pos_rank'] == rank)]
        if not baseline_row.empty: return baseline_row['points'].values[0]
        fallback = df[df['pos'] == pos]
        if not fallback.empty: return fallback['points'].min()
        return 0

    baseline_starter_pts = {pos: get_baseline_pts(pos, BASELINES_STARTER) for pos in df['pos'].unique()}
    baseline_waiver_pts = {pos: get_baseline_pts(pos, BASELINES_WAIVER) for pos in df['pos'].unique()}

    df['VOR_Starter'] = df.apply(lambda row: row['points'] - baseline_starter_pts.get(row['pos'], 0), axis=1)
    df['VOR_Waiver'] = df.apply(lambda row: row['points'] - baseline_waiver_pts.get(row['pos'], 0), axis=1)

    df['CV'] = df['sd_pts'] / df['points']
    df['CV'] = df['CV'].replace([np.inf, -np.inf], np.nan).fillna(0)
    df['Risk'] = df['CV'].round(2)

    pos_value_pool = {}
    for pos in df['pos'].unique():
        max_pts = df[df['pos'] == pos]['points'].max()
        baseline_pts = baseline_starter_pts.get(pos, 0)
        pos_value_pool[pos] = max_pts - baseline_pts

    max_pool = max(pos_value_pool.values()) if pos_value_pool else 1
    dynamic_weights = {pos: (val / max_pool) for pos, val in pos_value_pool.items()}

    df['z_score'] = 0.0
    for pos in df['pos'].unique():
        max_starter_rank = BASELINES_STARTER.get(pos, 12)
        starter_mask = (df['pos'] == pos) & (df['original_pos_rank'] <= max_starter_rank)
        starters_df = df[starter_mask]
        
        if not starters_df.empty:
            mean_pts = starters_df['points'].mean()
            std_pts = starters_df['points'].std()
            if std_pts > 0:
                pos_mask = df['pos'] == pos
                raw_z = (df.loc[pos_mask, 'points'] - mean_pts) / std_pts
                df.loc[pos_mask, 'z_score'] = raw_z * dynamic_weights.get(pos, 1.0)

    df['z_score'] = df['z_score'].round(2)

    def calculate_pos_gap_tiers(pos_df):
        pos = pos_df['pos'].iloc[0]
        n_tiers = 8 if pos in ['QB', 'RB', 'WR'] else 6 if pos == 'TE' else 3 
        
        if len(pos_df) < n_tiers:
            pos_df['tier_label'] = "Tier 1"
            return pos_df
            
        pos_df = pos_df.sort_values('VOR_Starter', ascending=False).reset_index(drop=True)
        pos_df['drop'] = pos_df['VOR_Starter'].diff(-1)
        
        n_cliffs = n_tiers - 1
        if pos == 'QB': cliff_indices = pos_df['drop'][:24].nlargest(n_cliffs).index.tolist()
        else: cliff_indices = pos_df['drop'][:-1].nlargest(n_cliffs).index.tolist()
            
        cliff_indices.sort()
        tiers = []
        current_tier = 1
        for idx in range(len(pos_df)):
            tiers.append(f"Tier {current_tier}")
            if idx in cliff_indices: current_tier += 1
                
        pos_df['tier_label'] = tiers
        return pos_df.drop(columns=['drop'])

    df_list = []
    for pos in df['pos'].unique():
        pos_df = df[df['pos'] == pos].copy()
        pos_df = calculate_pos_gap_tiers(pos_df)
        df_list.append(pos_df)
    df = pd.concat(df_list)

    df['RPV (%)'] = 0.0
    for (pos, tier), group in df.groupby(['pos', 'tier_label']):
        tier_mean = group['points'].mean()
        if tier_mean > 0:
            df.loc[group.index, 'RPV (%)'] = ((group['points'] - tier_mean) / tier_mean) * 100
    df['RPV (%)'] = df['RPV (%)'].round(1)

    df = df.sort_values(by='z_score', ascending=False).reset_index(drop=True)
    df['Ovr Rank'] = "#" + (df.index + 1).astype(str)
    
    return df, dynamic_weights

full_board, computed_weights = calculate_dynamic_metrics(working_df)
available_df = full_board[~full_board['player'].isin(st.session_state.drafted_names)].copy()


# --- 4. SIDEBAR APPENDS ---
with st.sidebar:
    st.markdown("---")
    st.header("🛒 Meine Queue")
    if not st.session_state.queue:
        st.write("*Noch keine Spieler in der Queue.*")
    else:
        for i, p in enumerate(st.session_state.queue):
            col_name, col_up, col_down, col_del = st.columns([5, 1, 1, 1])
            col_name.write(f"**{i+1}.** {p}")
            
            if col_up.button("↑", key=f"up_{p}") and i > 0:
                st.session_state.queue[i], st.session_state.queue[i-1] = st.session_state.queue[i-1], st.session_state.queue[i]
                st.rerun()
                
            if col_down.button("↓", key=f"down_{p}") and i < len(st.session_state.queue) - 1:
                st.session_state.queue[i], st.session_state.queue[i+1] = st.session_state.queue[i+1], st.session_state.queue[i]
                st.rerun()
                
            if col_del.button("❌", key=f"rm_{p}"):
                st.session_state.queue.remove(p)
                st.rerun()

    st.markdown("---")
    st.header("📈 Live Scarcity-Faktor")
    st.caption("Berechnete Knappheit pro Position:")
    for pos in ['RB', 'WR', 'QB', 'TE']:
        if pos in computed_weights:
            st.metric(pos, f"{computed_weights[pos]:.2f}x")

    st.markdown("---")
    st.markdown(f"### ⏱️ On the Clock:")
    if current_team_up == my_team_id:
        st.success(f"**DU BIST DRAN! (Pick {current_pick_num})**")
        st.info(f"Dein nächster Pick ist in **{picks_until_next} Picks**.")
    else:
        st.info(f"Team {current_team_up} wählt... (Pick {current_pick_num})")
        st.write(f"Du bist dran in **{next_own_pick - current_pick_num} Picks**.")

    st.markdown("---")
    st.header("🔮 Draft Orakel")
    lookahead_picks = [current_pick_num + i for i in range(int(TEAMS_IN_LEAGUE))]
    upcoming_teams = [get_team_for_pick(p) for p in lookahead_picks if get_team_for_pick(p) != my_team_id]
    unique_upcoming = list(dict.fromkeys(upcoming_teams))
    
    enemy_needs = {'RB': 0, 'WR': 0, 'TE': 0, 'QB': 0}
    for t_id in upcoming_teams:
        t_roster = [p['pos'] for p in st.session_state.history if p['team_id'] == t_id]
        if t_roster.count('RB') < rb_spots: enemy_needs['RB'] += 1
        if t_roster.count('WR') < wr_spots: enemy_needs['WR'] += 1
        if t_roster.count('TE') < te_spots: enemy_needs['TE'] += 1
        if t_roster.count('QB') < qb_spots: enemy_needs['QB'] += 1
    
    st.write(f"*Nächste {TEAMS_IN_LEAGUE} Picks (Teams: {', '.join(map(str, unique_upcoming))})*")
    if enemy_needs['RB'] >= 4: st.error(f"⚠️ **RB Run Gefahr!** Gegner suchen noch {enemy_needs['RB']} RBs.")
    if enemy_needs['WR'] >= 4: st.warning(f"👀 **WR Need:** Gegner suchen noch {enemy_needs['WR']} WRs.")
    if enemy_needs['TE'] >= 2: st.info(f"💡 Gegner suchen noch {enemy_needs['TE']} TEs.")
    if sum(enemy_needs.values()) <= 4: st.success("Gegner sind gut besetzt. BPA draften.")


# --- 5. FARBEN & GRAFIK FUNKTIONEN ---
def get_tier_color(tier_str):
    try: tier_num = int(tier_str.split()[1])
    except: tier_num = 1
        
    color_map = {
        1: '#FF1A1A', 2: '#FFA500', 3: '#FFFF00', 
        4: '#32CD32', 5: '#1E90FF', 6: '#FF69B4'
    }
    if tier_num in color_map: return color_map[tier_num]
    else:
        gray_val = max(180 - (tier_num - 7) * 25, 50)
        return f"rgb({gray_val}, {gray_val}, {gray_val})"

@st.dialog("Aktion für Spieler")
def draft_confirmation_dialog(player_name):
    st.markdown(f"Was möchtest du mit **{player_name}** tun?")
    col1, col2, col3 = st.columns(3)
    
    if col1.button("✅ Draften", use_container_width=True):
        draft_player(player_name)
        st.rerun()
        
    if col2.button("⭐ Zur Queue", use_container_width=True):
        if player_name not in st.session_state.queue:
            st.session_state.queue.append(player_name)
            st.session_state.last_msg = f"⭐ {player_name} zur Queue hinzugefügt!"
        st.rerun()
        
    if col3.button("❌ Abbrechen", use_container_width=True):
        st.rerun()

def draft_player(search_string):
    matches = available_df[available_df['player'].str.contains(search_string, case=False, na=False)]
    if not matches.empty:
        exact_match = matches[matches['player'].str.lower() == search_string.lower()]
        player_row = exact_match.iloc[0] if not exact_match.empty else matches.iloc[0]
        
        st.session_state.drafted_names = st.session_state.drafted_names + [player_row['player']]
        
        if player_row['player'] in st.session_state.queue:
            st.session_state.queue.remove(player_row['player'])
            
        runden_nummer = (current_pick_num - 1) // TEAMS_IN_LEAGUE + 1
        pick_in_runde = (current_pick_num - 1) % TEAMS_IN_LEAGUE + 1
        
        new_pick = {
            'overall_pick': current_pick_num, 'pick_str': f"{int(runden_nummer)}.{int(pick_in_runde):02d}",
            'team_id': current_team_up, 'player': player_row['player'], 
            'pos': player_row['pos'], 'team': player_row['team'],
            'pos_rank': player_row['Pos Rank']
        }
        st.session_state.history = st.session_state.history + [new_pick]
        st.session_state.last_msg = f"✅ Pick {int(runden_nummer)}.{int(pick_in_runde):02d}: {player_row['player']} gedraftet!"
    else:
        st.error("⚠️ Spieler nicht gefunden oder bereits weg.")

def plot_position_cliff(pos):
    pos_all = full_board[full_board['pos'] == pos].sort_values('original_pos_rank')
    available_this_pos = pos_all[~pos_all['player'].isin(st.session_state.drafted_names)]
    
    if available_this_pos.empty:
        st.write(f"Keine {pos} mehr verfügbar.")
        return

    first_avail_idx = available_this_pos.index[0]
    start_idx = pos_all.index.get_loc(first_avail_idx)
    window = pos_all.iloc[start_idx : start_idx + 15].copy()
    
    def get_marker_symbol(rank):
        if rank == BASELINES_STARTER.get(pos): return 'star'
        if rank == BASELINES_WAIVER.get(pos): return 'diamond'
        return 'circle'
        
    window['color'] = window.apply(lambda r: '#d3d3d3' if r['player'] in st.session_state.drafted_names else get_tier_color(r['tier_label']), axis=1)
    window['symbol'] = window['original_pos_rank'].apply(get_marker_symbol)

    fig = go.Figure()

    tiers_in_window = window['tier_label'].unique()
    for tier in tiers_in_window:
        tier_data = window[window['tier_label'] == tier]
        if not tier_data.empty:
            min_vor = tier_data['VOR_Starter'].min()
            fig.add_hline(y=min_vor - 1.5, line_dash="dash", line_color="#2c3e50", opacity=0.5,
                          annotation_text=f"End of {tier}", annotation_position="bottom left")

    fig.add_trace(go.Scatter(
        x=window['original_pos_rank'],
        y=window['VOR_Starter'],
        mode='markers+text',
        marker=dict(
            size=[(15 + (r * 20)) * (1.5 if sym != 'circle' else 1.0) if not pd.isna(r) else 15 for r, sym in zip(window['Risk'], window['symbol'])], 
            color=window['color'],
            symbol=window['symbol'], 
            line=dict(width=1.5, color='DarkSlateGrey'),
            opacity=1.0
        ),
        text=[f"{n.split()[0][0]}.{n.split()[1][:3]}" if len(n.split())>=2 else n[:4] for n in window['player']],
        textposition="top center",
        hovertext=[f"<b>{row['player']}</b><br>Rank: {pos}{int(row['original_pos_rank'])}<br>VOR: {row['VOR_Starter']:.1f}<br>Z-Score: {row['z_score']}<br>Tier: {row['tier_label']}" for _, row in window.iterrows()],
        hoverinfo="text"
    ))

    fig.update_layout(
        title=f"Value Cliffs & Tiers: {pos}",
        xaxis_title=f"{pos} Position Rank",
        yaxis_title="VOR Starter Value",
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
        plot_bgcolor='rgba(0,0,0,0)',
        showlegend=False
    )
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='LightGray')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='LightGray')
    
    st.plotly_chart(fig, use_container_width=True)


# --- 6. HAUPTBEREICH (UI) ---
col_title, col_undo = st.columns([3, 1])
with col_title:
    st.title("🏈FF Draft Assistant 26🏈")
with col_undo:
    if st.button("↩️ Letzten Pick zurück"):
        if st.session_state.history:
            last = st.session_state.history[-1]
            st.session_state.history = st.session_state.history[:-1]
            st.session_state.drafted_names = [name for name in st.session_state.drafted_names if name != last['player']]
            st.session_state.last_msg = f"↩️ Pick rückgängig: {last['player']} ist zurück auf dem Board."
            
            if last['team_id'] == my_team_id and last['player'] not in st.session_state.queue:
                st.session_state.queue.append(last['player'])
                
            st.rerun()

if 'last_msg' in st.session_state:
    if "rückgängig" in st.session_state.last_msg: st.warning(st.session_state.last_msg)
    elif "Queue" in st.session_state.last_msg: st.info(st.session_state.last_msg)
    else: st.success(st.session_state.last_msg)
    del st.session_state.last_msg

# === VONA SIMULATOR ===
if current_team_up == my_team_id: picks_to_wait = subsequent_own_pick - current_pick_num - 1 
else: picks_to_wait = next_own_pick - current_pick_num

picks_to_wait = max(0, picks_to_wait)

sim_base_df = available_df.copy()
sim_base_df['Rank_ADP'] = sim_base_df['adp'].rank(ascending=True)
sim_base_df['Rank_Z'] = sim_base_df['z_score'].rank(ascending=False)
sim_base_df['Rank_VOR'] = sim_base_df['VOR_Waiver'].rank(ascending=False)
sim_base_df['Opponent_Score'] = (sim_base_df['Rank_ADP'] * ADP_W) + (sim_base_df['Rank_Z'] * Z_W) + (sim_base_df['Rank_VOR'] * VOR_W)
sim_base_df = sim_base_df.sort_values('Opponent_Score', ascending=True)

available_df['VONA'] = available_df['VOR_Waiver'].round(1)

top_candidates = available_df.sort_values('z_score', ascending=False).head(75)
vona_dict = {}

for idx, row in top_candidates.iterrows():
    pos = row['pos']
    pts = row['points']
    player_name = row['player']
    
    sim_board = sim_base_df[sim_base_df['player'] != player_name]
    if picks_to_wait > 0:
        sim_board = sim_board.iloc[picks_to_wait:]
        
    remaining_pos = sim_board[sim_board['pos'] == pos]
    
    if not remaining_pos.empty: vona = pts - remaining_pos['points'].max()
    else: vona = row['VOR_Waiver']
        
    vona_dict[player_name] = round(vona, 1)

available_df['VONA'] = available_df['player'].map(vona_dict).fillna(available_df['VONA'])

# --- TABS ---
st.markdown("### 📋 Draft Board")
search_term = st.text_input("🔍 Spielersuche (filtert das Board):", "")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Overall", "RB", "WR", "TE", "QB", "👥 Liga-Roster"])

# Dynamische Spaltenauswahl basierend auf Checkboxen
cols_overall = ['Ovr Rank', 'player', 'Pos Rank', 'points', 'team', 'z_score', 'VONA', 'VOR_Starter', 'Risk'] + selected_adps + selected_sources
rename_overall = {'z_score': 'Z-Score', 'VOR_Starter': 'VOR (Start)', 'Risk': 'Risk (CV)', 'points': 'Points'}

with tab1:
    sort_by = st.radio("🔀 Sortieren nach:", ["Z-Score", "VONA", "VOR_Starter"], horizontal=True)
    display_df = available_df[cols_overall].copy()
    
    if search_term:
        display_df = display_df[display_df['player'].str.contains(search_term, case=False, na=False)]
    
    if sort_by == "Z-Score": display_df = display_df.sort_values('z_score', ascending=False)
    elif sort_by == "VONA": display_df = display_df.sort_values('VONA', ascending=False)
    elif sort_by == "VOR_Starter": display_df = display_df.sort_values('VOR_Starter', ascending=False)
        
    display_df = display_df.rename(columns=rename_overall)
    display_df['VOR (Start)'] = display_df['VOR (Start)'].round(1) 
    display_df['Points'] = display_df['Points'].round(1)
    display_df = display_df.head(50)
    
    st.caption("💡 Klicke auf einen Spieler, um das Draft-Popup zu öffnen (dort kannst du ihn auch in die Queue legen).")
    
    event = st.dataframe(display_df, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
    
    if len(event.selection.rows) > 0:
        selected_player = display_df.iloc[event.selection.rows[0]]['player']
        draft_confirmation_dialog(selected_player)

cols_pos = ['Pos Rank', 'player', 'points', 'team', 'tier_label', 'VONA', 'VOR_Starter', 'RPV (%)', 'VOR_Waiver', 'Risk'] + selected_adps + selected_sources
rename_pos = {'tier_label': 'Tier', 'VOR_Starter': 'VOR (Start)', 'VOR_Waiver': 'VOR (Waiver)', 'Risk': 'Risk (CV)', 'points': 'Points'}

def render_pos_tab(pos):
    plot_position_cliff(pos)
    pos_df = available_df[available_df['pos'] == pos][cols_pos].copy()
    
    if search_term:
        pos_df = pos_df[pos_df['player'].str.contains(search_term, case=False, na=False)]
        
    pos_df = pos_df.sort_values('VOR_Starter', ascending=False).rename(columns=rename_pos)
    pos_df['VOR (Start)'] = pos_df['VOR (Start)'].round(1)
    pos_df['VOR (Waiver)'] = pos_df['VOR (Waiver)'].round(1)
    pos_df['Points'] = pos_df['Points'].round(1)
    
    display_pos_df = pos_df.head(15)
    
    event = st.dataframe(display_pos_df, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
    if len(event.selection.rows) > 0:
        selected_player = display_pos_df.iloc[event.selection.rows[0]]['player']
        draft_confirmation_dialog(selected_player)

with tab2: render_pos_tab('RB')
with tab3: render_pos_tab('WR')
with tab4: render_pos_tab('TE')
with tab5: render_pos_tab('QB')

# --- LIGA ROSTER TAB ---
with tab6:
    st.subheader("Roster aller Teams")
    cols = st.columns(4) 
    for t_id in range(1, int(TEAMS_IN_LEAGUE) + 1):
        col_idx = (t_id - 1) % 4
        team_roster = [p for p in st.session_state.history if p['team_id'] == t_id]
        with cols[col_idx]:
            if t_id == my_team_id: st.markdown(f"**🟢 Team {t_id} (DU)**")
            else: st.markdown(f"**Team {t_id}**")
            if not team_roster: st.write("*Leer*")
            else:
                for pick in team_roster: 
                    display_pos = pick.get('pos_rank', pick['pos']) 
                    st.write(f"`{display_pos}` {pick['player']}")
            st.markdown("---")

# --- HISTORY ---
st.markdown("---")
if st.session_state.history:
    st.subheader("📜 Letzte Picks")
    cols = st.columns(5)
    for i, p in enumerate(reversed(st.session_state.history[-5:])):
        own_pick_marker = "🟢 " if p['team_id'] == my_team_id else ""
        display_pos = p.get('pos_rank', p['pos'])
        cols[i].metric(f"{own_pick_marker}{p['pick_str']} (Team {p['team_id']})", p['player'], display_pos)
