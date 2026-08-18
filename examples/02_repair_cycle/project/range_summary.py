import json, sys

values=[abs(int(x)) for x in sys.argv[1:]]
if not values:
    raise SystemExit(2)
print(json.dumps({"count":len(values),"min":min(values),"max":max(values),"sum":sum(values),"average":sum(values)/len(values)}))
