Re-review the CURRENT TODO in this same read-only session. The original review rules and immutable decision protocol remain authoritative.

Do not reuse the previous verdict after repair. Re-check only requirements affected by new executor/validator evidence plus criteria that were previously unresolved. Reuse unchanged evidence already inspected and do not broaden scope.

New executor evidence:
{{ task.last_output[-3000:] }}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}

Only report concrete requirements that remain unsatisfied now. Do not repeat a previous missing item if it is now satisfied. If no blocking item remains, PASS.
