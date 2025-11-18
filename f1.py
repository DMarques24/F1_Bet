from urllib.request import urlopen
import json
import time
import random
from collections import defaultdict
from datetime import datetime

# ---------------- Configuráveis ----------------
PONTOS_F1 = {
    1: 25, 2: 18, 3: 15, 4: 12, 5: 10,
    6: 8, 7: 6, 8: 4, 9: 2, 10: 1
}

# Pesos do Modelo B por sessão (ajusta se quiseres)
SESSION_WEIGHTS = {
    "Practice": 1,
    "Qualifying": 3,
    "Sprint Qualifying": 2,
    "Sprint": 4
}
PAST_RACES_WEIGHT = 5

API_SLEEP = 0.2
TOTAL_CORRIDAS = 24
MONTE_CARLO_SIMULATIONS = 10000
# ------------------------------------------------

def get_json(url):
    time.sleep(API_SLEEP)
    response = urlopen(url)
    return json.loads(response.read().decode('utf-8'))

# --- APIs ---
def get_sessions_all(year):
    return get_json(f"https://api.openf1.org/v1/sessions?year={year}")

def get_race_sessions(year):
    return get_json(f"https://api.openf1.org/v1/sessions?session_name=Race&year={year}")

def get_positions(session_key):
    return get_json(f"https://api.openf1.org/v1/session_result?session_key={session_key}")

def get_driver_info_api(number, session_key=None):
    url = f"https://api.openf1.org/v1/drivers?driver_number={number}"
    if session_key:
        url += f"&session_key={session_key}"
    return get_json(url)

# ----------------- Helpers -----------------
def parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None

def normalize_session_name(s):
    if not s:
        return ""
    s = s.strip()
    # pad common variants
    mappings = {
        "Sprint Qualifying": "Sprint Qualifying",
        "Sprint": "Sprint",
        "Qualifying": "Qualifying",
        "Practice": "Practice",
        "Race": "Race",
        "Free Practice 1": "Practice",
        "FP1": "Practice",
        "FP2": "Practice",
        "FP3": "Practice",
    }
    for k,v in mappings.items():
        if s.lower().startswith(k.lower()):
            return v
    return s

# Cache wrappers to reduce repeated API calls
_positions_cache = {}
_driver_cache = {}

def positions_cached(session_key):
    if session_key in _positions_cache:
        return _positions_cache[session_key]
    data = get_positions(session_key)
    _positions_cache[session_key] = data
    return data

def driver_info_cached(number, session_key=None):
    key = (number, session_key)
    if key in _driver_cache:
        return _driver_cache[key]
    try:
        data = get_driver_info_api(number, session_key)
    except Exception:
        data = []
    if not data:
        try:
            data2 = get_driver_info_api(number, None)
        except Exception:
            data2 = []
        data = data2 or []
    if not data:
        info = {"name_acronym": f"P{number}", "team_name": "Unknown"}
    else:
        info = {
            "name_acronym": data[0].get("name_acronym") or data[0].get("name_acrony") or f"P{number}",
            "team_name": data[0].get("team_name", "Unknown")
        }
    _driver_cache[key] = info
    return info

# ---------------- Core functions (separadas) ----------------

def collect_current_points_and_driverinfo(year):
    """Retorna (pontos_pilotos:dict(driver->pts), drivers_info:dict(driver->{name_acronym,team_name}), race_sessions_ordered:list)."""
    race_sessions = get_race_sessions(year)
    # ordenar corridas por data_start se possível
    race_list = []
    for r in race_sessions:
        date = parse_date(r.get("date_start"))
        race_list.append({
            "meeting_key": r.get("meeting_key"),
            "session_key": r.get("session_key"),
            "date": date,
            "raw": r
        })
    race_list.sort(key=lambda x: (x["date"] is None, x["date"]))

    pontos_pilotos = {}
    drivers_info = {}

    for r in race_list:
        sk = r.get("session_key")
        if not sk:
            continue
        results = positions_cached(sk)
        for rec in results:
            dn = rec.get("driver_number")
            pos = rec.get("position")
            if dn is None:
                continue
            if dn not in drivers_info:
                drivers_info[dn] = driver_info_cached(dn, sk)
            if isinstance(pos, int) and pos in PONTOS_F1:
                pontos_pilotos.setdefault(dn, 0)
                pontos_pilotos[dn] += PONTOS_F1[pos]

    return pontos_pilotos, drivers_info, race_list

def simular_campeonato(pontos_atual, corridas_restantes, simulacoes=MONTE_CARLO_SIMULATIONS):
    participantes = list(pontos_atual.keys())
    if not participantes:
        return {}
    pesos = {p: max(1, pontos_atual.get(p, 0)) for p in participantes}
    vencedores = {p: 0 for p in participantes}

    for _ in range(simulacoes):
        pontos_sim = pontos_atual.copy()
        for _ in range(corridas_restantes):
            corrida = random.choices(
                participantes,
                weights=[pesos[p] for p in participantes],
                k=len(participantes)
            )
            for pos, participante in enumerate(corrida[:10], start=1):
                pontos_sim[participante] = pontos_sim.get(participante, 0) + PONTOS_F1[pos]
        campeao = max(pontos_sim, key=lambda p: pontos_sim[p])
        vencedores[campeao] += 1

    return {p: (vencedores.get(p,0) / simulacoes) * 100 for p in participantes}

# ---------------- Model B: scores por sessão ----------------

def compute_session_scores(session_key):
    """score invertido por posição para uma sessão: driver -> score (1º = n_participants ...)."""
    results = positions_cached(session_key)
    positions = [r.get("position") for r in results if isinstance(r.get("position"), int)]
    if not positions:
        return {}
    n = len(positions)
    scores = {}
    for r in results:
        dn = r.get("driver_number")
        pos = r.get("position")
        if dn is None or not isinstance(pos, int):
            continue
        scores[dn] = max(0, n - (pos - 1))
    return scores

def aggregate_past_races_scores(race_list_ordered, up_to_index):
    agg = defaultdict(int)
    for i in range(up_to_index):
        race = race_list_ordered[i]
        sk = race.get("session_key")
        if not sk:
            continue
        res = positions_cached(sk)
        positions = [r.get("position") for r in res if isinstance(r.get("position"), int)]
        if not positions:
            continue
        n = len(positions)
        for r in res:
            dn = r.get("driver_number")
            pos = r.get("position")
            if dn is None or not isinstance(pos, int):
                continue
            agg[dn] += max(0, n - (pos - 1))
    return dict(agg)

def predict_per_race_probabilities_modelB(year):
    sessions_all = get_sessions_all(year)
    race_sessions = get_race_sessions(year)

    # meetings map
    meetings = {}
    for s in sessions_all:
        mk = s.get("meeting_key")
        meetings.setdefault(mk, []).append(s)

    # ordered races
    race_list = []
    for r in race_sessions:
        race_list.append({
            "meeting_key": r.get("meeting_key"),
            "session_key": r.get("session_key"),
            "date": parse_date(r.get("date_start")),
            "raw": r
        })
    race_list.sort(key=lambda x: (x["date"] is None, x["date"]))

    drivers_cache_local = {}

    per_race_probs = []  # list of dicts

    for idx, race in enumerate(race_list):
        mk = race["meeting_key"]
        race_sk = race["session_key"]
        raw = race["raw"]

        meeting_sessions = meetings.get(mk, [])
        type_to_sk = {}
        for s in meeting_sessions:
            name = s.get("session_type") or s.get("session_name") or ""
            name = normalize_session_name(name)
            type_to_sk[name] = s.get("session_key")

        # accumulate weighted scores
        driver_scores = defaultdict(float)

        # per-session scores
        for session_name, weight in SESSION_WEIGHTS.items():
            sk = type_to_sk.get(session_name)
            if not sk:
                continue
            sess_scores = compute_session_scores(sk)
            for dn, sc in sess_scores.items():
                driver_scores[dn] += sc * weight

        # past races
        past_scores = aggregate_past_races_scores(race_list, idx)
        for dn, sc in past_scores.items():
            driver_scores[dn] += sc * PAST_RACES_WEIGHT

        # championship points baseline from past races (for drivers that exist but no scores)
        champ_points = defaultdict(int)
        for i in range(0, idx):
            race_p = race_list[i]
            sk = race_p.get("session_key")
            if not sk:
                continue
            results = positions_cached(sk)
            for rec in results:
                dn = rec.get("driver_number")
                pos = rec.get("position")
                if dn is None or not isinstance(pos, int):
                    continue
                if pos in PONTOS_F1:
                    champ_points[dn] += PONTOS_F1[pos]

        # fallback baseline
        for dn, pts in champ_points.items():
            if dn not in driver_scores:
                driver_scores[dn] = pts * 0.5

        pilotos = set(driver_scores.keys()) | set(champ_points.keys())

        # fill drivers_cache_local names
        for dn in pilotos:
            if dn not in drivers_cache_local:
                drivers_cache_local[dn] = driver_info_cached(dn, race_sk)

        total_score = sum(driver_scores.get(dn, 0) for dn in pilotos)
        probabilities = {}
        if total_score <= 0:
            n = len(pilotos) if pilotos else 0
            for dn in pilotos:
                probabilities[dn] = 100.0 / n if n > 0 else 0.0
        else:
            for dn in pilotos:
                probabilities[dn] = (driver_scores.get(dn, 0) / total_score) * 100.0

        ordered = sorted(probabilities.items(), key=lambda x: x[1], reverse=True)

        per_race_probs.append({
            "meeting_key": mk,
            "race_session_key": race_sk,
            "race_name": raw.get("country") or raw.get("meeting_name") or f"Meeting {mk}",
            "date": race.get("date"),
            "probabilities": ordered,
            "driver_scores": dict(driver_scores)
        })

    return per_race_probs, drivers_cache_local

# ---------------- Presentation functions ----------------

def pretty_print_championship_tables(pontos_pilotos, drivers_info, prob_pilotos, pontos_equipas, prob_equipas):
    print("\n=== CLASSIFICAÇÃO + PROBABILIDADES (PILOTOS) ===\n")
    print(f"{'Piloto':<8} {'Nome':<8} {'Pontos':<8} {'Prob Campeão':<12}")
    print("-" * 40)
    for piloto, pts in sorted(pontos_pilotos.items(), key=lambda x: x[1], reverse=True):
        nome = drivers_info.get(piloto, {}).get("name_acronym", str(piloto))
        prob = prob_pilotos.get(piloto, 0)
        print(f"{piloto:<8} {nome:<8} {pts:<8} {prob:10.2f}%")

    print("\n=== CLASSIFICAÇÃO + PROBABILIDADES (EQUIPAS) ===\n")
    print(f"{'Equipa':<20} {'Pontos':<8} {'Prob Campeão':<12}")
    print("-" * 44)
    for equipa, pts in sorted(pontos_equipas.items(), key=lambda x: x[1], reverse=True):
        prob = prob_equipas.get(equipa, 0)
        print(f"{equipa:<20} {pts:<8} {prob:10.2f}%")

def pretty_print_favorites_per_race(per_race_probs, drivers_cache, top_n=1):
    print("\n=== FAVORITOS POR CORRIDA ===\n")
    for i, race in enumerate(per_race_probs, start=1):
        date_str = race["date"].strftime("%Y-%m-%d") if race["date"] else "Unknown date"
        top = race["probabilities"][:top_n]
        if not top:
            print(f"Corrida {i}: {race['race_name']} ({date_str}) — sem dados")
            continue
        # show the top favorite (or top_n if chosen)
        line = f"Corrida {i}: {race['race_name']} ({date_str}) — "
        favorites = []
        for dn, prob in top:
            info = drivers_cache.get(dn, {"name_acronym": str(dn), "team_name": "Unknown"})
            name = info.get("name_acronym", str(dn))
            favorites.append(f"{name} {prob:.2f}%")
        line += " | ".join(favorites)
        print(line)

# ---------------- Main (organizada) ----------------

def main():
    year = 2025
    print(f"=== Calculando previsões F1 {year} ===\n")

    # 1) Coletar pontos e info
    pontos_pilotos, drivers_info, race_list = collect_current_points_and_driverinfo(year)

    # 2) Campeonato de pilotos com Monte-Carlo
    corridas_realizadas = len(race_list)
    corridas_restantes = max(0, TOTAL_CORRIDAS - corridas_realizadas)
    prob_pilotos = simular_campeonato(pontos_pilotos, corridas_restantes)

    # 3) Construtores: soma por equipa
    pontos_equipas = {}
    for piloto, pts in pontos_pilotos.items():
        team = drivers_info.get(piloto, {}).get("team_name", "Unknown")
        pontos_equipas.setdefault(team, 0)
        pontos_equipas[team] += pts
    prob_equipas = simular_campeonato(pontos_equipas, corridas_restantes)

    # 4) Previsões por corrida (Modelo B)
    per_race_probs, drivers_cache_local = predict_per_race_probabilities_modelB(year)

    # 5) Impressão dos resultados
    # - Tabelas campeonato pilotos + equipas
    print("\n=== TABELAS DE CAMPEONATO ===")
    print(f"Corridas realizadas: {corridas_realizadas}")
    print(f"Corridas restantes (estimadas): {corridas_restantes}\n")

    # pretty_print usa agora os parâmetros correctos — passamos tudo
    pretty_print_championship_tables(pontos_pilotos, drivers_info, prob_pilotos, pontos_equipas, prob_equipas)

    # - Favoritos por corrida: mostramos o piloto com maior probabilidade para cada corrida
    pretty_print_favorites_per_race(per_race_probs, drivers_cache_local, top_n=1)

    print("\nFim.")

if __name__ == "__main__":
    main()
