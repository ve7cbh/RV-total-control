cat > ~/check_winddir.flux << 'EOF'
from(bucket: "rvtc")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "weewx")
  |> filter(fn: (r) => r._field == "windDir")
  |> last()
EOF