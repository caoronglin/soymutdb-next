/**
 * The console's current instance, resolved from the registry.
 *
 * Default is the local instance: the console is the local deployment's admin
 * surface, and every write it performs is a write to this deployment. A remote
 * registration can be *displayed* as the current target (registration-only),
 * but it never grants authority over the remote database — the local-only
 * default is what keeps a console with no trust configuration from looking
 * like it can operate a peer.
 */
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue, type ComputedRef } from "vue";

import { listSpeciesInstances, type SpeciesInstance } from "@soymutdb/api-client";

import { useAdminInstanceContext } from "../stores/instance-context";

export interface AdminInstanceContext {
  instances: ComputedRef<SpeciesInstance[]>;
  localInstance: ComputedRef<SpeciesInstance | null>;
  currentInstance: ComputedRef<SpeciesInstance | null>;
  isRemote: ComputedRef<boolean>;
  isLoading: ComputedRef<boolean>;
  isError: ComputedRef<boolean>;
  selectInstance: (code: string | null) => void;
}

export function useInstanceContext(): AdminInstanceContext {
  const store = useAdminInstanceContext();
  const query = useQuery({
    // Same key as the instances page: one registry read feeds both surfaces.
    queryKey: ["admin", "species-instances"],
    queryFn: listSpeciesInstances,
    staleTime: 30_000,
    retry: false,
  });

  const instances = computed<SpeciesInstance[]>(() => toValue(query.data)?.items ?? []);
  const localInstance = computed(
    () => instances.value.find((instance) => instance.is_local) ?? null,
  );
  const currentInstance = computed(
    () =>
      instances.value.find((instance) => instance.code === store.selectedCode) ??
      localInstance.value,
  );
  const isRemote = computed(
    () => Boolean(currentInstance.value) && !currentInstance.value?.is_local,
  );

  return {
    instances,
    localInstance,
    currentInstance,
    isRemote,
    isLoading: computed(() => toValue(query.isLoading)),
    isError: computed(() => toValue(query.isError)),
    selectInstance: (code: string | null) => store.select(code),
  };
}
