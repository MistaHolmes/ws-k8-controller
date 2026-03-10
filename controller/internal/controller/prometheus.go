package controller

import (
	"encoding/json"
	"net/http"
	"strconv"
)

func queryTotalConnections() (int, error) {

	resp, err := http.Get("http://prometheus.monitoring.svc.cluster.local:9090/api/v1/query?query=sum(active_connections)")
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()

	var result struct {
		Data struct {
			Result []struct {
				Value []interface{} `json:"value"`
			} `json:"result"`
		} `json:"data"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return 0, err
	}

	if len(result.Data.Result) == 0 {
		return 0, nil
	}

	valueStr := result.Data.Result[0].Value[1].(string)
	valueFloat, _ := strconv.ParseFloat(valueStr, 64)

	return int(valueFloat), nil
}
