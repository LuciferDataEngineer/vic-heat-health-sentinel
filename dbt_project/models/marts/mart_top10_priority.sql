select *
from {{ ref('stg_lga_priority') }}
order by priority_score desc
limit 10
