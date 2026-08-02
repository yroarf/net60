
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
import hdbscan
import warnings
import gc

warnings.filterwarnings('ignore')
gc.collect()
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (10, 6)

# ============================================================
# 1. LEITURA E PREPARAÇÃO DOS DADOS
# ============================================================
file_path = "C:/Users/yroar/OneDrive/Curso MBA FGV/Projeto do TCC/planilha_tic_domicilios_descr_v1.csv"

print("Carregando dados...")
df = pd.read_csv(file_path, sep=';')
df.columns = df.iloc[0]
df = df[1:].reset_index(drop=True)

# ============================================================
# 2. FILTRAGEM: Idosos (60+) com C1 válido
# ============================================================
df['FAIXA_ETARIA'] = pd.to_numeric(df['FAIXA_ETARIA'], errors='coerce')
df['C1'] = pd.to_numeric(df['C1'], errors='coerce')

df_idosos = df[(df['FAIXA_ETARIA'] == 6) & (df['C1'].isin([0, 1]))].copy()
print(f"Idosos (60+) com C1 válido: {len(df_idosos):,}")

# ============================================================
# 3. ENGENHARIA DE VARIÁVEIS (CORRIGIDA)
# ============================================================
habilidades_cols = [f'I1A_{chr(65 + i)}' for i in range(12)]

for col in habilidades_cols:
    df_idosos[col] = pd.to_numeric(df_idosos[col], errors='coerce')

# Escore apenas com respostas válidas
df_idosos['escore_digital'] = df_idosos[habilidades_cols].applymap(
    lambda x: 1 if x == 1 else 0
).sum(axis=1)

# Filtro mais brando
mask_muitos_invalidos = (df_idosos[habilidades_cols] > 96).sum(axis=1) > 6
df_idosos = df_idosos[~mask_muitos_invalidos].copy()

df_idosos[habilidades_cols] = df_idosos[habilidades_cols].replace([97, 98, 99], 0).fillna(0).astype(int)
df_idosos['escore_digital'] = df_idosos[habilidades_cols].sum(axis=1)

df_idosos['usou_govbr'] = ((df_idosos['G5_A'] == 1) | (df_idosos['G5_B'] == 1)).astype(int)
df_idosos['usou_ia'] = (df_idosos['C13A'] == 1).astype(int)

print(f"Idosos após limpeza: {len(df_idosos):,}")

# ============================================================
# 4. CLUSTERING COM HDBSCAN
# ============================================================
features_cluster = habilidades_cols + ['usou_govbr', 'usou_ia']

X = df_idosos[features_cluster].copy()
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

clusterer = hdbscan.HDBSCAN(
    min_cluster_size=15,
    min_samples=5,
    cluster_selection_epsilon=0.4
)

df_idosos['cluster_hdbscan'] = clusterer.fit_predict(X_scaled)

# ============================================================
# 5. ROTULAÇÃO HÍBRIDA
# ============================================================
cluster_stats = df_idosos.groupby('cluster_hdbscan')['escore_digital'].agg(['mean', 'count']).reset_index()
cluster_stats.columns = ['cluster_hdbscan', 'escore_medio', 'n']

def rotular_cluster(row):
    escore = row['escore_medio']
    if row['cluster_hdbscan'] == -1:
        return 'Ruído / Atípico'
    elif escore < 3:
        return 'Muito Baixa Capacidade'
    elif escore < 6:
        return 'Baixa Capacidade'
    elif escore < 9:
        return 'Média Capacidade'
    else:
        return 'Alta Capacidade'

cluster_stats['rotulo'] = cluster_stats.apply(rotular_cluster, axis=1)
rotulo_dict = dict(zip(cluster_stats['cluster_hdbscan'], cluster_stats['rotulo']))
df_idosos['perfil_digital'] = df_idosos['cluster_hdbscan'].map(rotulo_dict)

# ============================================================
# 6. POPULAÇÃO PONDERADA (USANDO PESO)
# ============================================================
print("\n" + "="*70)
print("ESTIMATIVA DE POPULAÇÃO DE IDOSOS (PONDERADA)")
print("="*70)

# Converter PESO para numérico
df_idosos['PESO'] = pd.to_numeric(df_idosos['PESO'], errors='coerce')

# População total estimada de idosos
pop_total_idosos = df_idosos['PESO'].sum()
print(f"\nPopulação total estimada de idosos (60+): {pop_total_idosos:,.0f} pessoas")

# População por perfil digital
pop_por_perfil = df_idosos.groupby('perfil_digital')['PESO'].sum().reset_index()
pop_por_perfil.columns = ['Perfil Digital', 'População Estimada']
pop_por_perfil['% da População'] = (pop_por_perfil['População Estimada'] / pop_total_idosos * 100).round(1)
pop_por_perfil = pop_por_perfil.sort_values('População Estimada', ascending=False)

print("\nPopulação estimada por Perfil Digital:")
print(pop_por_perfil.to_string(index=False))

# ============================================================
# 7. IMPORTÂNCIA DE VARIÁVEIS
# ============================================================
print("\n" + "="*70)
print("IMPORTÂNCIA DE VARIÁVEIS")
print("="*70)

X_imp = df_idosos[features_cluster]
y_imp = df_idosos['cluster_hdbscan']

rf = RandomForestClassifier(n_estimators=300, max_depth=10, random_state=42, class_weight='balanced')
rf.fit(X_imp, y_imp)

importancia_global = pd.DataFrame({
    'Variável': features_cluster,
    'Importância': rf.feature_importances_
}).sort_values('Importância', ascending=False)

print("\nTop 8 Variáveis mais importantes (Global):")
print(importancia_global.head(8).round(4))

# ============================================================
# 8. SUBGRUPOS COM ALTO POTENCIAL
# ============================================================
potencial = df_idosos[df_idosos['perfil_digital'].isin(['Baixa Capacidade', 'Média Capacidade'])].copy()

potencial['alto_potencial'] = (
    (potencial['escore_digital'] >= 3) &
    (potencial['J3'] == 1) &
    (potencial['usou_govbr'] == 0) &
    (potencial['I1A_J'] + potencial['I1A_K'] + potencial['I1A_L'] >= 1)
)

pop_alto_potencial = potencial[potencial['alto_potencial']]['PESO'].sum()
pop_baixa_media = potencial['PESO'].sum()

print("\n" + "="*70)
print("SUBGRUPOS COM MAIOR POTENCIAL DE DESENVOLVIMENTO")
print("="*70)
print(f"População em clusters Baixa/Média Capacidade: {pop_baixa_media:,.0f}")
print(f"População com ALTO POTENCIAL: {pop_alto_potencial:,.0f}")
print(f"Percentual do grupo Baixa/Média: {(pop_alto_potencial / pop_baixa_media * 100):.1f}%")

# ============================================================
# 9. VISUALIZAÇÕES GRÁFICAS
# ============================================================
print("\nGerando gráficos...")

# Gráfico 1: População por Perfil Digital
plt.figure(figsize=(10, 6))
sns.barplot(data=pop_por_perfil, x='População Estimada', y='Perfil Digital', palette='viridis')
plt.title('População Estimada de Idosos por Perfil Digital', fontsize=14, fontweight='bold')
plt.xlabel('População Estimada')
plt.ylabel('')
for i, v in enumerate(pop_por_perfil['População Estimada']):
    plt.text(v + 50000, i, f'{v:,.0f}', va='center', fontsize=10)
plt.tight_layout()
plt.savefig('populacao_por_perfil.png', dpi=300, bbox_inches='tight')
plt.close()

# Gráfico 2: Distribuição do Escore Digital
plt.figure(figsize=(10, 5))
sns.histplot(df_idosos['escore_digital'], bins=13, kde=True, color='steelblue')
plt.title('Distribuição do Escore de Habilidades Digitais entre Idosos', fontsize=14, fontweight='bold')
plt.xlabel('Escore Digital (0 a 12)')
plt.ylabel('Frequência')
plt.axvline(df_idosos['escore_digital'].mean(), color='red', linestyle='--', label=f'Média: {df_idosos["escore_digital"].mean():.1f}')
plt.legend()
plt.tight_layout()
plt.savefig('distribuicao_escore.png', dpi=300, bbox_inches='tight')
plt.close()

# Gráfico 3: Importância das Variáveis (Top 8)
plt.figure(figsize=(9, 6))
sns.barplot(data=importancia_global.head(8), x='Importância', y='Variável', palette='rocket')
plt.title('Importância das Habilidades Digitais (Random Forest)', fontsize=14, fontweight='bold')
plt.xlabel('Importância Relativa')
plt.tight_layout()
plt.savefig('importancia_variaveis.png', dpi=300, bbox_inches='tight')
plt.close()

# Gráfico 4: Comparação Alto Potencial vs Resto
labels = ['Alto Potencial', 'Outros (Baixa/Média)']
sizes = [pop_alto_potencial, pop_baixa_media - pop_alto_potencial]
colors = ['#2ecc71', '#e74c3c']
explode = (0.05, 0)

plt.figure(figsize=(7, 7))
plt.pie(sizes, explode=explode, labels=labels, colors=colors, autopct='%1.1f%%',
        shadow=True, startangle=90, textprops={'fontsize': 12})
plt.title('Proporção de Idosos com Alto Potencial\n(dentro do grupo Baixa/Média Capacidade)',
          fontsize=13, fontweight='bold')
plt.tight_layout()
plt.savefig('alto_potencial_proporcao.png', dpi=300, bbox_inches='tight')
plt.close()

print("\nGráficos salvos com sucesso:")
print("- populacao_por_perfil.png")
print("- distribuicao_escore.png")
print("- importancia_variaveis.png")
print("- alto_potencial_proporcao.png")

# Salvar base final
df_idosos.to_csv("resultado_hdbscan_hibrido_idosos_com_graficos.csv", index=False)
print("\nBase de dados salva: resultado_hdbscan_hibrido_idosos_com_graficos.csv")