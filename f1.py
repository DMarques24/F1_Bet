from urllib.request import urlopen
import json
import time
import random

PONTOS_F1 = {
    1: 25,
    2: 18,
    3: 15,
    4: 12,
    5: 10,
    6: 8,
    7: 6,
    8: 4,
    9: 2,
    10: 1
}

def get_json(url):
    time.sleep(0.2)
    response = urlopen(url)
    return json.loads(response.read().decode('utf-8'))

def get_sessions(year):
    return get_json(f"https://api.openf1.org/v1/sessions?session_name=Race&year={year}")

def get_practice():
    return get_json(f"https://api.openf1.org/v1/sessions?session_name=Practice&year={year}")


def get_positions(session_key):
    return get_json(f"https://api.openf1.org/v1/session_result?session_key={session_key}")

def get_driver_info(number, session_key):
    url = f"https://api.openf1.org/v1/drivers?driver_number={number}&session_key={session_key}"
    data = get_json(url)
    if not data:
        return {"name_acronym": f"P{number}", "team_name": "Unknown"}
    return {
        "name_acronym": data[0].get("name_acronym", f"error"),
        "team_name": data[0].get("team_name", "Unknown")
    }

# ============================================================
#      FUNÇÃO DO MODELO MONTE-CARLO
# ============================================================

def simular_campeonato(pontos_atual, corridas_restantes, simulacoes=10000):
    participantes = list(pontos_atual.keys())

    pesos = {p: max(1, pontos_atual[p]) for p in participantes}
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
                pontos_sim[participante] += PONTOS_F1[pos]

        campeao = max(pontos_sim, key=lambda p: pontos_sim[p])
        vencedores[campeao] += 1

    return {p: (vencedores[p] / simulacoes) * 100 for p in participantes}


# ============================================================
#                         MAIN
# ============================================================

def main():
    year = 2025
    print("=== Pontos F1 2025 ===\n")

    sessions = get_sessions(year)
    pontos_pilotos = {}
    drivers_info = {}

    # Coletar os pontos reais já disputados
    for sessao in sessions:
        session_key = sessao.get("session_key")
        resultados = get_positions(session_key)

        for r in resultados:
            driver_number = r.get("driver_number")
            position = r.get("position")

            # Guardar info do piloto 1x por piloto
            if driver_number not in drivers_info:
                drivers_info[driver_number] = get_driver_info(driver_number, session_key)

            if position in PONTOS_F1:
                if driver_number not in pontos_pilotos:
                    pontos_pilotos[driver_number] = 0
                pontos_pilotos[driver_number] += PONTOS_F1[position]

    TOTAL_CORRIDAS = 24
    corridas_restantes = TOTAL_CORRIDAS - len(sessions)

    # ===== MONTE CARLO PILOTOS =====
    prob_pilotos = simular_campeonato(pontos_pilotos, corridas_restantes)

    # ============================================================
    #              CAMPEONATO DE EQUIPAS
    # ============================================================

    pontos_equipas = {}
    for piloto, pts in pontos_pilotos.items():
        equipa = drivers_info[piloto]["team_name"]
        if equipa not in pontos_equipas:
            pontos_equipas[equipa] = 0
        pontos_equipas[equipa] += pts

    # Monte-Carlo para equipas
    prob_equipas = simular_campeonato(pontos_equipas, corridas_restantes)

    # ============================
    #  TABELA FINAL PILOTOS
    # ============================
    print("\n=== CLASSIFICAÇÃO + PROBABILIDADES (PILOTOS) ===\n")

    print(f"{'Piloto':<10} {'Nome':<10} {'Pontos':<10} {'Prob Campeão':<15}")
    print("-" * 60)

    for piloto, pontos in sorted(pontos_pilotos.items(), key=lambda x: x[1], reverse=True):
        nome = drivers_info[piloto]["name_acronym"]
        prob = prob_pilotos.get(piloto, 0)
        print(f"{piloto:<10} {nome:<10} {pontos:<10} {prob:>10.2f}%")

    # ============================
    #  TABELA FINAL EQUIPAS
    # ============================
    print("\n=== CLASSIFICAÇÃO + PROBABILIDADES (EQUIPAS) ===\n")

    print(f"{'Equipa':<20} {'Pontos':<10} {'Prob Campeão':<15}")
    print("-" * 50)

    for equipa, pontos in sorted(pontos_equipas.items(), key=lambda x: x[1], reverse=True):
        prob = prob_equipas.get(equipa, 0)
        print(f"{equipa:<20} {pontos:<10} {prob:>10.2f}%")

    print("\nFim.")


if __name__ == "__main__":
    main()
