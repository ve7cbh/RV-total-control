cat > ~/evo2212_query.flux << 'EOF'
from(bucket: "rvtc")
  |> range(start: -3d)
  |> filter(fn: (r) => r._measurement == "inverter")
  |> pivot(rowKey: ["_time"], columnKey: ["topic"], valueColumn: "_value")
EOF