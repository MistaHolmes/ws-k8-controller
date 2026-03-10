package controller

import (
	"context"
	"math"
	"sync"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"

	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"

	autoscalingv1alpha1 "star/controller/api/v1alpha1"
)

type replicaHistory struct {
	Timestamp time.Time
	Replicas  int32
}

var (
	historyMu        sync.Mutex
	scaleDownHistory = make(map[types.NamespacedName][]replicaHistory)
)

func getStabilizedDesiredReplicas(nn types.NamespacedName, newDesired int32, window time.Duration) int32 {
	if window <= 0 {
		return newDesired
	}

	historyMu.Lock()
	defer historyMu.Unlock()

	now := time.Now()
	history := scaleDownHistory[nn]

	var validHistory []replicaHistory
	for _, h := range history {
		if now.Sub(h.Timestamp) <= window {
			validHistory = append(validHistory, h)
		}
	}
	validHistory = append(validHistory, replicaHistory{Timestamp: now, Replicas: newDesired})
	scaleDownHistory[nn] = validHistory

	stabilized := newDesired
	for _, h := range validHistory {
		if h.Replicas > stabilized {
			stabilized = h.Replicas
		}
	}

	return stabilized
}

// StatefulAutoscalerReconciler reconciles a StatefulAutoscaler object
type StatefulAutoscalerReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// RBAC for CRD
// +kubebuilder:rbac:groups=autoscaling.star.local,resources=statefulautoscalers,verbs=get;list;watch;update;patch
// +kubebuilder:rbac:groups=autoscaling.star.local,resources=statefulautoscalers/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=autoscaling.star.local,resources=statefulautoscalers/finalizers,verbs=update

// RBAC for Deployments
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;update;patch

func (r *StatefulAutoscalerReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {

	var autoscaler autoscalingv1alpha1.StatefulAutoscaler
	if err := r.Get(ctx, req.NamespacedName, &autoscaler); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	if autoscaler.Spec.TargetRef.Name == "" {
		return ctrl.Result{}, nil
	}

	var deployment appsv1.Deployment
	if err := r.Get(ctx,
		types.NamespacedName{
			Name:      autoscaler.Spec.TargetRef.Name,
			Namespace: req.Namespace,
		},
		&deployment); err != nil {
		return ctrl.Result{}, err
	}

	currentReplicas := int32(0)
	if deployment.Spec.Replicas != nil {
		currentReplicas = *deployment.Spec.Replicas
	}

	totalConnections, err := queryTotalConnections()
	if err != nil {
		return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
	}

	if autoscaler.Spec.TargetConnectionsPerPod == 0 {
		return ctrl.Result{RequeueAfter: 10 * time.Second}, nil
	}

	rawDesired := int32(math.Ceil(
		float64(totalConnections) /
			float64(autoscaler.Spec.TargetConnectionsPerPod),
	))

	if autoscaler.Spec.MinReplicas != nil && rawDesired < *autoscaler.Spec.MinReplicas {
		rawDesired = *autoscaler.Spec.MinReplicas
	}

	if autoscaler.Spec.MaxReplicas != nil && rawDesired > *autoscaler.Spec.MaxReplicas {
		rawDesired = *autoscaler.Spec.MaxReplicas
	}

	window := time.Duration(autoscaler.Spec.ScaleDownCooldownSeconds) * time.Second
	desired := getStabilizedDesiredReplicas(req.NamespacedName, rawDesired, window)

	if desired > currentReplicas {
		step := autoscaler.Spec.MaxScaleUpStep
		if step > 0 && desired-currentReplicas > step {
			desired = currentReplicas + step
		}
	} else if desired < currentReplicas {
		step := autoscaler.Spec.MaxScaleDownStep
		if step > 0 && currentReplicas-desired > step {
			desired = currentReplicas - step
		}
	}

	if desired != currentReplicas {
		deployment.Spec.Replicas = &desired
		if err := r.Update(ctx, &deployment); err != nil {
			return ctrl.Result{}, err
		}
	}

	return ctrl.Result{RequeueAfter: 5 * time.Second}, nil
}

func (r *StatefulAutoscalerReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&autoscalingv1alpha1.StatefulAutoscaler{}).
		Complete(r)
}
