/** Evolutionary Lineage tree view using react-d3-tree. */

import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import Tree from "react-d3-tree";
import { fetchEvolutionLineage } from "../api/client";
import type { LineageNode } from "../types";

interface TreeDatum {
  name: string;
  attributes?: Record<string, string>;
  children?: TreeDatum[];
}

/** Build a forest of tree data from the flat lineage list. */
function buildTree(nodes: LineageNode[]): TreeDatum[] {
  const map = new Map<string, TreeDatum>();
  const childMap = new Map<string, string[]>();

  // Create tree datums and record parent-child relationships.
  for (const n of nodes) {
    map.set(n.persona_id, {
      name: n.persona_name,
      attributes: {
        role: n.role_class,
        gen: String(n.generation),
        status: n.status,
        balance: n.credit_balance.toFixed(1),
      },
      children: [],
    });
    if (n.parent_persona_id) {
      const existing = childMap.get(n.parent_persona_id) ?? [];
      existing.push(n.persona_id);
      childMap.set(n.parent_persona_id, existing);
    }
  }

  // Wire children.
  for (const [parentId, childIds] of childMap.entries()) {
    const parent = map.get(parentId);
    if (parent) {
      for (const cid of childIds) {
        const child = map.get(cid);
        if (child) parent.children!.push(child);
      }
    }
  }

  // Roots are nodes without parents.
  const roots: TreeDatum[] = [];
  for (const n of nodes) {
    if (!n.parent_persona_id) {
      const datum = map.get(n.persona_id);
      if (datum) roots.push(datum);
    }
  }

  // If the list is empty return a placeholder.
  if (roots.length === 0) {
    return [{ name: "No lineage data" }];
  }

  // If there are multiple roots, wrap them under a virtual root.
  if (roots.length === 1) return roots;
  return [{ name: "NEXUS", children: roots }];
}

const statusColor: Record<string, string> = {
  active: "#10b981",
  deprecated: "#6b7280",
};

export default function EvolutionaryLineage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["evolution-lineage"],
    queryFn: fetchEvolutionLineage,
  });

  const treeData = useMemo(
    () => buildTree(data?.nodes ?? []),
    [data],
  );

  const renderNode = useCallback(
    ({ nodeDatum }: { nodeDatum: TreeDatum }) => {
      const status = nodeDatum.attributes?.status ?? "";
      const fill = statusColor[status] ?? "#94a3b8";
      return (
        <g>
          <circle r={10} fill={fill} stroke="#334155" strokeWidth={1.5} />
          <text
            fill="#e2e8f0"
            x={16}
            y={4}
            style={{ fontSize: 11, fontWeight: 500 }}
          >
            {nodeDatum.name}
          </text>
          {nodeDatum.attributes?.role && (
            <text fill="#94a3b8" x={16} y={18} style={{ fontSize: 9 }}>
              {nodeDatum.attributes.role} (gen {nodeDatum.attributes.gen})
            </text>
          )}
        </g>
      );
    },
    [],
  );

  if (isLoading)
    return (
      <div style={{ color: "#64748b" }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
          Evolutionary Lineage
        </h2>
        Loading...
      </div>
    );

  if (error)
    return (
      <div style={{ color: "#ef4444" }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
          Evolutionary Lineage
        </h2>
        Error: {String(error)}
      </div>
    );

  return (
    <>
      <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
        Evolutionary Lineage
      </h2>
      <div style={{ flex: 1, minHeight: 300 }}>
        <Tree
          data={treeData}
          orientation="vertical"
          pathFunc="step"
          translate={{ x: 200, y: 40 }}
          separation={{ siblings: 1.2, nonSiblings: 1.5 }}
          renderCustomNodeElement={(rd3tProps: any) =>
            renderNode(rd3tProps)
          }
          nodeSize={{ x: 180, y: 80 }}
          rootNodeClassName="node__root"
          branchNodeClassName="node__branch"
          leafNodeClassName="node__leaf"
        />
      </div>
    </>
  );
}
