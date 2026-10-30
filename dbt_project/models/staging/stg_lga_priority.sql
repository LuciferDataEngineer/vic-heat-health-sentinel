select
    lga_code,
    lga_name,
    district,
    persons,
    people_65_plus,
    priority_score,
    very_hot_days_ahead,
    health_alert_days_ahead,
    forecast_max_c,
    anomaly_c,
    avg_summer_very_hot_days,
    avg_summer_health_alert_days,
    poor_air_days
from read_parquet('{{ env_var("VHHS_ROOT") }}/data/marts/lga_priority.parquet')
