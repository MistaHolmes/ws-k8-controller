/*
Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

type DrainPolicy struct {
	Enabled             bool  `json:"enabled"`
	TimeoutSeconds      int32 `json:"timeoutSeconds"`
	MaxConcurrentDrains int32 `json:"maxConcurrentDrains"`
}

// StatefulAutoscalerSpec defines the desired state of StatefulAutoscaler
type StatefulAutoscalerSpec struct {
	TargetRef corev1.ObjectReference `json:"targetRef"`

	MinReplicas *int32 `json:"minReplicas,omitempty"`
	MaxReplicas *int32 `json:"maxReplicas,omitempty"`

	TargetConnectionsPerPod int32 `json:"targetConnectionsPerPod"`

	MaxScaleUpStep   int32 `json:"maxScaleUpStep"`
	MaxScaleDownStep int32 `json:"maxScaleDownStep"`

	ScaleUpCooldownSeconds   int32 `json:"scaleUpCooldownSeconds"`
	ScaleDownCooldownSeconds int32 `json:"scaleDownCooldownSeconds"`

	Drain DrainPolicy `json:"drain"`
}

// StatefulAutoscalerStatus defines the observed state of StatefulAutoscaler.
type StatefulAutoscalerStatus struct {
	// INSERT ADDITIONAL STATUS FIELD - define observed state of cluster
	// Important: Run "make" to regenerate code after modifying this file

	// For Kubernetes API conventions, see:
	// https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/api-conventions.md#typical-status-properties

	// conditions represent the current state of the StatefulAutoscaler resource.
	// Each condition has a unique type and reflects the status of a specific aspect of the resource.
	//
	// Standard condition types include:
	// - "Available": the resource is fully functional
	// - "Progressing": the resource is being created or updated
	// - "Degraded": the resource failed to reach or maintain its desired state
	//
	// The status of each condition is one of True, False, or Unknown.
	// +listType=map
	// +listMapKey=type
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status

// StatefulAutoscaler is the Schema for the statefulautoscalers API
type StatefulAutoscaler struct {
	metav1.TypeMeta `json:",inline"`

	// metadata is a standard object metadata
	// +optional
	metav1.ObjectMeta `json:"metadata,omitzero"`

	// spec defines the desired state of StatefulAutoscaler
	// +required
	Spec StatefulAutoscalerSpec `json:"spec"`

	// status defines the observed state of StatefulAutoscaler
	// +optional
	Status StatefulAutoscalerStatus `json:"status,omitzero"`
}

// +kubebuilder:object:root=true

// StatefulAutoscalerList contains a list of StatefulAutoscaler
type StatefulAutoscalerList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitzero"`
	Items           []StatefulAutoscaler `json:"items"`
}

func init() {
	SchemeBuilder.Register(&StatefulAutoscaler{}, &StatefulAutoscalerList{})
}
