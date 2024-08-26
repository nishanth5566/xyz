import { getClient } from "@/api/AxiosClient";
import { WorkflowParameter } from "@/api/types";
import { Form, FormControl, FormField, FormItem } from "@/components/ui/form";
import { useCredentialGetter } from "@/hooks/useCredentialGetter";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useParams } from "react-router-dom";
import { WorkflowParameterInput } from "./WorkflowParameterInput";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/use-toast";
import { PlayIcon, ReloadIcon } from "@radix-ui/react-icons";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type Props = {
  workflowParameters: Array<WorkflowParameter>;
  initialValues: Record<string, unknown>;
};

function RunWorkflowForm({ workflowParameters, initialValues }: Props) {
  const { workflowPermanentId } = useParams();
  const credentialGetter = useCredentialGetter();
  const queryClient = useQueryClient();
  const form = useForm({
    defaultValues: initialValues,
  });

  const runWorkflowMutation = useMutation({
    mutationFn: async (values: Record<string, unknown>) => {
      const client = await getClient(credentialGetter);
      return client
        .post(`/workflows/${workflowPermanentId}/run`, {
          data: values,
          proxy_location: "RESIDENTIAL",
        })
        .then((response) => response.data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["workflowRuns"],
      });
      toast({
        variant: "success",
        title: "Workflow run started",
        description: "The workflow run has been started successfully",
      });
    },
    onError: (error) => {
      toast({
        variant: "destructive",
        title: "Failed to start workflow run",
        description: error.message,
      });
    },
  });

  function onSubmit(values: Record<string, unknown>) {
    const parsedValues = Object.fromEntries(
      Object.entries(values).map(([key, value]) => {
        const parameter = workflowParameters?.find(
          (parameter) => parameter.key === key,
        );
        if (parameter?.workflow_parameter_type === "json") {
          try {
            return [key, JSON.parse(value as string)];
          } catch {
            console.error("Invalid JSON"); // this should never happen, it should fall to form error
            return [key, value];
          }
        }
        // can improve this via the type system maybe
        if (
          parameter?.workflow_parameter_type === "file_url" &&
          value !== null &&
          typeof value === "object" &&
          "s3uri" in value
        ) {
          return [key, value.s3uri];
        }
        return [key, value];
      }),
    );
    runWorkflowMutation.mutate(parsedValues);
  }

  return (
    <div>
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-8">
          <Table>
            <TableHeader className="bg-slate-elevation2 text-slate-400 [&_tr]:border-b-0">
              <TableRow className="rounded-lg px-6 [&_th:first-child]:pl-6 [&_th]:py-4">
                <TableHead className="w-1/3 text-sm text-slate-400">
                  Parameter Name
                </TableHead>
                <TableHead className="w-1/3 text-sm text-slate-400">
                  Description
                </TableHead>
                <TableHead className="w-1/3 text-sm text-slate-400">
                  Input
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {workflowParameters?.map((parameter) => {
                return (
                  <FormField
                    key={parameter.key}
                    control={form.control}
                    name={parameter.key}
                    rules={{
                      validate: (value) => {
                        if (
                          parameter.workflow_parameter_type === "json" &&
                          typeof value === "string"
                        ) {
                          try {
                            JSON.parse(value);
                            return true;
                          } catch (e) {
                            return "Invalid JSON";
                          }
                        }
                      },
                    }}
                    render={({ field }) => {
                      return (
                        <TableRow className="[&_td:first-child]:pl-6 [&_td:last-child]:pr-6 [&_td]:py-4">
                          <TableCell className="w-1/3">
                            <div className="flex h-8 w-fit items-center rounded-sm bg-slate-elevation3 p-3">
                              {parameter.key}
                            </div>
                          </TableCell>
                          <TableCell className="w-1/3">
                            <div>{parameter.description}</div>
                          </TableCell>
                          <TableCell className="w-1/3">
                            <FormItem>
                              <FormControl>
                                <WorkflowParameterInput
                                  type={parameter.workflow_parameter_type}
                                  value={field.value}
                                  onChange={field.onChange}
                                />
                              </FormControl>
                              {form.formState.errors[parameter.key] && (
                                <div className="text-destructive">
                                  {
                                    form.formState.errors[parameter.key]
                                      ?.message
                                  }
                                </div>
                              )}
                            </FormItem>
                          </TableCell>
                        </TableRow>
                      );
                    }}
                  />
                );
              })}
            </TableBody>
          </Table>
          <div className="flex justify-end">
            <Button type="submit" disabled={runWorkflowMutation.isPending}>
              {runWorkflowMutation.isPending && (
                <ReloadIcon className="mr-2 h-4 w-4 animate-spin" />
              )}
              {!runWorkflowMutation.isPending && (
                <PlayIcon className="mr-2 h-4 w-4" />
              )}
              Run workflow
            </Button>
          </div>
        </form>
      </Form>
    </div>
  );
}

export { RunWorkflowForm };
