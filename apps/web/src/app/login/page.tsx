"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { productConfig } from "@/lib/config";
import { useLogin } from "@/lib/use-auth";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const login = useLogin();

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <Card className="w-full max-w-sm border-t-2 border-t-primary">
        <CardHeader className="gap-2 pb-5 pt-6">
          <div className="eyebrow text-primary">{productConfig.parentBrand}</div>
          <CardTitle className="font-serif text-2xl font-normal italic tracking-tight text-foreground">
            {productConfig.productName}
          </CardTitle>
          <CardDescription>Invite-only access. Sign in with your account.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              login.mutate({ email, password });
            }}
          >
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {login.isError && (
              <p className="text-sm text-red-600">
                {login.error instanceof ApiError ? String(login.error.detail) : "Sign-in failed."}
              </p>
            )}
            <Button type="submit" disabled={login.isPending} className="w-full">
              {login.isPending ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
