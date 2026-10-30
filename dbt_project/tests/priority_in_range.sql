select lga_code, priority_score, persons
from {{ ref('stg_lga_priority') }}
where priority_score < 0
   or priority_score > 100
   or persons < 100
